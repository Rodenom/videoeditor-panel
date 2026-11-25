#!/usr/bin/env python3
"""Самотест панели — ловит регрессии до того, как их поймает байер.

Запуск:  python3 selftest.py
Ничего не заливает и не трогает боевые данные: сеть только к локальной панели,
YouTube-загрузка замокана, временные файлы в /tmp.

Проверяет ровно те места, которые ломались на практике:
  • синтаксис и импорт app.py
  • нормализация прокси (host:port:user:pass и др.)
  • вариации заголовков (уникальность на объёме)
  • уникализация видео (ffmpeg-фильтры реально работают)
  • все ТРИ массовых режима дают уникальные файлы и заголовки
  • дружелюбные тексты ошибок (прокси/токен/лимит)
  • генерация ТЗ не хардкодит домен
"""
import os, sys, subprocess, hashlib, importlib.util, tempfile, shutil, traceback, time

HERE = os.path.dirname(os.path.abspath(__file__))
OK, FAIL = [], []

def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('  ✅ ' if cond else '  ❌ ') + name + (('  — ' + detail) if detail and not cond else ''))

def load_app():
    spec = importlib.util.spec_from_file_location('appmod', os.path.join(HERE, 'app.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def mk_video(path, size='360x640', dur=2, audio=True):
    cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'testsrc=size=%s:rate=25:duration=%d' % (size, dur)]
    if audio:
        cmd += ['-f', 'lavfi', '-i', 'sine=frequency=300:duration=%d' % dur]
    cmd += ['-c:v', 'libx264']
    if audio:
        cmd += ['-c:a', 'aac', '-shortest']
    cmd += [path]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path

def main():
    print('\n🩺 Самотест панели\n')

    print('1. Синтаксис и импорт')
    try:
        import ast
        ast.parse(open(os.path.join(HERE, 'app.py')).read())
        check('app.py парсится', True)
    except Exception as e:
        check('app.py парсится', False, str(e)[:120]); print('\nДальше нет смысла.'); return 1
    try:
        app = load_app()
        check('app.py импортируется', True)
    except Exception as e:
        check('app.py импортируется', False, str(e)[:160]); return 1

    # Учёт окна YouTube пишет в свой файл при каждой заливке. Уводим его во
    # временную папку: самотест не должен трогать боевые записи панели.
    import atexit
    _yt_dir = tempfile.mkdtemp(prefix='veyt_')
    atexit.register(shutil.rmtree, _yt_dir, True)
    app.YT_STATE_FILE = os.path.join(_yt_dir, 'yt_state.json')

    def yt_reset(**kw):
        st = app._yt_blank(time.time())
        st.update(kw)
        app._yt_save(st)
    yt_reset()

    print('\n2. Прокси: принимаем любой формат')
    cases = {
        '1.2.3.4:1080:user:pass': 'socks5://user:pass@1.2.3.4:1080',
        'user:pass@1.2.3.4:1080': 'socks5://user:pass@1.2.3.4:1080',
        'socks5://user:pass@1.2.3.4:1080': 'socks5://user:pass@1.2.3.4:1080',
        '1.2.3.4:1080': 'socks5://1.2.3.4:1080',
        '': '',
    }
    for raw, want in cases.items():
        got = app.normalize_proxy(raw)
        check('proxy %-32s' % (repr(raw)[:32]), got == want, 'получили %s, ждали %s' % (got, want))

    print('\n3. Заголовки: уникальны на объёме, текст байера сохранён')
    base = 'I Tried Waking Up at 5AM'
    v = [app.vary_text(base, i, True) for i in range(60)]
    check('60 вариантов уникальны', len(set(v)) == 60)
    check('текст байера в каждом', all(base in x for x in v))
    check('пустой ввод не падает', app.vary_text('', 3, True) == '')

    print('\n4. Уникализация видео (реальный ffmpeg)')
    tmp = tempfile.mkdtemp(prefix='vetest_')
    try:
        src = mk_video(os.path.join(tmp, 'src.mp4'))
        outs = []
        for i in range(3):
            d = os.path.join(tmp, 'u%d.mp4' % i)
            r = app.uniqueize_file(src, d, i)
            outs.append(hashlib.md5(open(r, 'rb').read()).hexdigest() if os.path.exists(r) else None)
        check('3 копии — разные байты', len(set(outs)) == 3 and all(outs))
        w, h, _ = app.get_video_info(os.path.join(tmp, 'u0.mp4'))
        check('размер сохранён (360x640)', (w, h) == (360, 640), '%sx%s' % (w, h))
        na = mk_video(os.path.join(tmp, 'na.mp4'), audio=False)
        r = app.uniqueize_file(na, os.path.join(tmp, 'na_u.mp4'), 0)
        check('видео без аудио не ломает', os.path.exists(r))
        bad = app.uniqueize_file(os.path.join(tmp, 'нет.mp4'), os.path.join(tmp, 'x.mp4'), 0)
        check('битый вход -> фоллбэк на оригинал', bad.endswith('нет.mp4'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('\n5. Все массовые режимы: уникальные файлы И заголовки')
    tmp = tempfile.mkdtemp(prefix='vemode_')
    # ВАЖНО: изолируем счётчики загрузок — иначе тестовые каналы копятся в
    # боевом uploads_today.json и упираются в дневной лимит (тест начинает
    # «падать» на ровном месте, а у байера сбиваются реальные счётчики).
    _counts = {'date': time.strftime('%Y-%m-%d'), 'counts': {}}
    # Все подменяемые функции сохраняем и возвращаем в finally — иначе заглушки
    # протекают в следующие секции и те молча проверяют не то, что думают.
    # journal_add тоже глушим: без этого тестовые ролики v1..v4 попадают в
    # боевой журнал Павла и он видит в панели ролики, которых не заливал.
    _STUBBED = ('load_uploads_today', 'save_uploads_today', 'increment_project_upload',
                'load_channels', 'save_channels', 'get_youtube_service', 'journal_add')
    _saved = {n: getattr(app, n) for n in _STUBBED}
    app.load_uploads_today = lambda: _counts
    app.save_uploads_today = lambda d: None
    app.increment_project_upload = lambda *a, **k: None
    app.journal_add = lambda *a, **k: None
    try:
        files = [{'path': mk_video(os.path.join(tmp, 'a.mp4')), 'fmt': '9:16', 'title': 'T'},
                 {'path': mk_video(os.path.join(tmp, 'b.mp4'), '640x640'), 'fmt': '1:1', 'title': 'T'}]
        import googleapiclient.http as gh
        gh.MediaFileUpload = lambda path, **k: type('M', (), {'_p': path})()
        app.load_channels = lambda user='pavel': {
            'A': {'name': 'A', 'token_file': 'x', 'proxy': '', 'project_id': None},
            'B': {'name': 'B', 'token_file': 'y', 'proxy': '', 'project_id': None}}
        app.save_channels = lambda *a, **k: None

        for mode_name, fn, kwargs in [
            ('ready_upload', app.ready_upload_to_youtube, dict(custom_title='T', custom_desc='D', uniqueize=True)),
            ('mass_upload', app.mass_upload_to_youtube, None),
        ]:
            cap = []
            class FR:
                def __init__(s, p, t): cap.append((hashlib.md5(open(p, 'rb').read()).hexdigest()[:10], t)); s._i = 'v%d' % len(cap)
                def next_chunk(s, num_retries=0): return (None, {'id': s._i})
            class FV:
                def insert(s, part, body, media_body): return FR(media_body._p, body['snippet']['title'])
            app.get_youtube_service = lambda token_file=None, proxy='': type('Y', (), {'videos': lambda s: FV()})()
            jid = 'st_' + mode_name
            app.MASS_UPLOAD_JOBS[jid] = {'status': 'pending', 'log': [], 'sets': [], 'total': 0, 'done': 0}
            try:
                if kwargs is not None:
                    fn(jid, files, 2, 'Cat', 'unlisted', 'pavel', **kwargs)
                else:
                    fn(jid, files, 2, 'T', 'D', 'unlisted', 'pavel', uniqueize=True)
                check('%s: 4 файла уникальны' % mode_name, len(set(h for h, _ in cap)) == 4, '%d уник.' % len(set(h for h, _ in cap)))
                check('%s: 4 заголовка уникальны' % mode_name, len(set(t for _, t in cap)) == 4)
                left = [f for f in os.listdir(app.OUTPUT_DIR) if f.startswith('uq_' + jid)]
                check('%s: временные файлы почищены' % mode_name, not left)
            except Exception as e:
                check('%s отработал' % mode_name, False, str(e)[:140])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for _n, _f in _saved.items():
            setattr(app, _n, _f)

    print('\n6. Прокси не теряется, если упал AI-запрос')
    # Регрессия из практики: AI-вызов снимал прокси, а восстанавливал ПОСЛЕ
    # запроса. Падение Claude (таймаут/429) оставляло окружение без прокси —
    # и видео уходило с реального IP панели вместо прокси аккаунта.
    tmp = tempfile.mkdtemp(prefix='vepx_')
    _PSTUB = ('load_uploads_today', 'save_uploads_today', 'increment_project_upload',
              'load_channels', 'save_channels', 'get_youtube_service', 'get_anthropic_key',
              'journal_add', 'proxy_preflight', 'bump_upload_count', 'BASE_DIR', 'OUTPUT_DIR',
              'UPLOADS_TODAY_FILE', 'JOURNAL_FILE')
    _psaved = {n: getattr(app, n) for n in _PSTUB}
    _pc = {'date': time.strftime('%Y-%m-%d'), 'counts': {}}
    app.load_uploads_today = lambda: _pc
    app.save_uploads_today = lambda d: None
    app.increment_project_upload = lambda *a, **k: None
    app.journal_add = lambda *a, **k: None
    try:
        vid = mk_video(os.path.join(tmp, 'p.mp4'), '320x180', 1)
        PROXY = 'socks5://user:pass@1.2.3.4:1080'
        seen = []
        class FR2:
            def __init__(s, *a): seen.append(os.environ.get('HTTPS_PROXY')); s._i = 'v%d' % len(seen)
            def next_chunk(s, num_retries=0): return (None, {'id': s._i})
        import googleapiclient.http as gh2
        gh2.MediaFileUpload = lambda path, **k: type('M', (), {'_p': path})()
        def _svc(token_file=None, proxy=''):
            if proxy:
                os.environ['HTTPS_PROXY'] = app.normalize_proxy(proxy)
            return type('Y', (), {'videos': lambda s: type('V', (), {'insert': lambda s2, **kw: FR2()})()})()
        # Мёртвый прокси называется сразу и не повторяется (v6.2): раньше панель
        # висела на «Подключаемся к каналу» минутами на каждом канале.
        _t0 = time.time()
        try:
            app.get_youtube_service_stubborn('x', 'socks5://u:p@127.0.0.1:9', [])
            _pd = None
        except Exception as _e:
            _pd = _e
        check('мёртвый прокси называется сразу, без минут ожидания',
              isinstance(_pd, app.ProxyDead) and time.time() - _t0 < 10
              and not app.is_network_error(_pd)
              and 'прокси 127.0.0.1:9' in app.friendly_upload_error(_pd), repr(_pd))
        app.proxy_preflight = lambda *a, **k: None    # адрес ниже выдуманный
        app.get_youtube_service = _svc
        app.load_channels = lambda user='pavel': {'A': {'name': 'A', 'token_file': 'x', 'proxy': PROXY, 'project_id': None}}
        app.save_channels = lambda *a, **k: None
        app.get_anthropic_key = lambda: 'sk-fake'
        import requests as _rq2
        _orig_post = _rq2.post
        _rq2.post = lambda *a, **k: (_ for _ in ()).throw(_rq2.exceptions.Timeout('fail'))
        try:
            jid2 = 'st_proxy'
            app.MASS_UPLOAD_JOBS[jid2] = {'status': 'pending', 'log': [], 'sets': [], 'total': 0, 'done': 0}
            os.environ['HTTPS_PROXY'] = PROXY
            app.ready_upload_to_youtube(jid2, [{'path': vid, 'fmt': '9:16'}], 1, 'C', 'unlisted', 'pavel')
            check('прокси пережил падение AI-запроса', bool(seen) and seen[0] == PROXY,
                  'в момент заливки было: %s' % (seen or 'заливки не было'))
        finally:
            _rq2.post = _orig_post
            os.environ.pop('HTTPS_PROXY', None)

        print('\n6б. Отказ YouTube: причина по-русски, квота снимает весь проект')
        # Вика, 19.11: на карточке канала стояло «ResumableUploadError:» и пусто —
        # ответ Google начинается с «<HttpError», браузер принимал его за тег.
        import json as _jq, copy as _cp, httplib2 as _h2
        from googleapiclient.errors import ResumableUploadError as _RUE
        def _refuse(code, reason, msg):
            return _RUE(_h2.Response({'status': str(code)}), _jq.dumps({'error': {
                'code': code, 'message': msg,
                'errors': [{'message': msg, 'domain': 'youtube', 'reason': reason}]}}).encode())
        _q = _refuse(403, 'quotaExceeded', 'The request cannot be completed because you have '
                     'exceeded your <a href="/youtube/v3/getting-started#quota">quota</a>.')
        _txt = app.friendly_upload_error(_q)
        check('квота проекта названа квотой', 'квота' in _txt and '<' not in _txt, _txt)
        _q429 = _refuse(429, 'rateLimitExceeded', "Quota exceeded for quota metric 'Video Uploads' and "
                        "limit 'Video Uploads per day' of service 'youtube.googleapis.com' for consumer "
                        "'project_number:1'.")
        _txt = app.friendly_upload_error(_q429)
        check('квота «Video Uploads per day» (429) названа квотой проекта, а не «частыми запросами»',
              'квота' in _txt and 'проект' in _txt and 'подожди несколько минут' not in _txt, _txt)
        check('429 по квоте распознаётся по тексту ошибки', app.is_project_quota(str(_q429)))
        _txt = app.friendly_upload_error(_refuse(403, 'forbidden', 'Forbidden <b>x</b>'))
        check('незнакомый отказ: код, причина и текст без разметки',
              '403' in _txt and 'forbidden' in _txt and '<' not in _txt, _txt)
        check('нет канала на аккаунте — так и сказано',
              'нет YouTube-канала' in app.friendly_upload_error(_refuse(401, 'youtubeSignupRequired', 'Unauthorized')))
        _src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
        check('проект канала читается из формы до того, как она стёрта',
              "resolve({proxyStr: proxy, loginHint: email, useOcto: true, projectId})" in _src
              and "project_id: projectId})" in _src
              and "getElementById('ch-project-sel')||{}).value" not in _src)
        check('карточка канала выводит ошибку текстом, а не разметкой',
              "String(ch.last_error).replace(/&/g,'&amp;').replace(/</g,'&lt;')" in open(os.path.join(HERE, 'app.py'), encoding='utf-8').read())

        app.BASE_DIR = tmp; app.OUTPUT_DIR = tmp
        app.bump_upload_count = lambda *a, **k: None
        yt_reset()
        _tried, _savedq = [], {}
        class FRQ:
            def __init__(s, tok): s.tok = tok
            def next_chunk(s, num_retries=0):
                _tried.append(s.tok)
                if s.tok in ('tA', 'tB'):
                    raise _q429
                return (None, {'id': 'vid_' + s.tok})
        app.get_youtube_service = lambda token_file=None, proxy='': type('Y', (), {
            'videos': lambda s: type('V', (), {'insert': lambda s2, **kw: FRQ(token_file)})()})()
        _chq = {'A': {'name': 'A', 'token_file': 'tA', 'proxy': '', 'project_id': 'p1'},
                'B': {'name': 'B', 'token_file': 'tB', 'proxy': '', 'project_id': 'p1'},
                'C': {'name': 'C', 'token_file': 'tC', 'proxy': '', 'project_id': 'p2'}}
        app.load_channels = lambda user='pavel': _cp.deepcopy(_chq)
        app.save_channels = lambda u, d: _savedq.update(d)
        jq = 'st_quota'
        app.MASS_UPLOAD_JOBS[jq] = {'status': 'pending', 'log': [], 'sets': [], 'total': 0, 'done': 0}
        app.auto_convert_and_upload(jq, vid, 1, 'C', 'unlisted', 'pavel',
                                    custom_title='T', custom_desc='D', as_is=True)
        _jl = app.MASS_UPLOAD_JOBS[jq]
        check('квота: канал не долбим повтором, соседа по проекту не трогаем',
              _tried == ['tA', 'tC'], 'обращались к: %s' % _tried)
        check('квота: ролик ушёл на канал другого проекта',
              [x['channel'] for x in _jl['sets']] == ['C'], str(_jl['log'][-6:]))
        check('квота: каналу не пишется «ошибка» — это не его поломка',
              not _savedq.get('A', {}).get('last_error'), str(_savedq.get('A')))
        check('квота: причина видна в журнале',
              any('❌' in l and 'квота' in l and '<' not in l for l in _jl['log']), str(_jl['log']))
        check('квота: проект закрыт до сброса суток Google, чужой проект открыт',
              (not app.yt_project_gate('p1')['ok']) and app.yt_project_gate('p2')['ok'])

        print('\n6в. Канал считается за 24 часа, отказы YouTube запоминаются')
        # Вика, 25.11: «залито 0/15, а він каже, що ліміт вичерпано». Счётчик панели
        # обнулялся в полночь, а YouTube считает за последние 24 часа; десять каналов
        # подряд ответили отказом, и каждый отказ стоил проекту запроса из квоты.
        H = 3600.0
        _now = time.time()
        yt_reset(times={'W15': [_now - 23 * H + i * H for i in range(15)],
                        'W13': [_now - 20 * H + i * H for i in range(13)],
                        'OLD': [_now - 25 * H, _now - 30 * H]})
        g = app.yt_channel_gate('W15', 1)
        check('15 заливок за 24 часа — канал закрыт без запроса к YouTube, названо время',
              (not g['ok']) and g['why'] == 'window' and g['count'] == 15
              and abs(g['until'] - (_now + 1 * H)) < 5, str(g))
        g1, g3 = app.yt_channel_gate('W13', 1), app.yt_channel_gate('W13', 3)
        check('13 из 15: один ролик влезает, набор из трёх — нет, и названо, когда влезет',
              g1['ok'] and (not g3['ok']) and abs(g3['until'] - (_now + 4 * H)) < 5, '%s | %s' % (g1, g3))
        check('заливки старше 24 часов в окно не идут',
              app.yt_channel_gate('OLD', 1)['count'] == 0 and app.yt_channel_gate('OLD', 3)['ok'])

        yt_reset(times={'R': [_now - 5 * H, _now - 4 * H]})
        rec = app.yt_note_refusal('R')
        g = app.yt_channel_gate('R', 1)
        check('первый отказ выдаёт лимит канала: залито 2 — значит, YouTube принимает 2 за сутки',
              rec.get('n') == 2 and rec.get('cap') == 2 and (not g['ok']) and g['why'] == 'cap'
              and g['cap'] == 2 and abs(g['until'] - (_now + 19 * H)) < 5, '%s | %s' % (rec, g))
        _why = app.yt_skip_reason('R', {'name': 'R'}, 1)
        check('закрытый канал пропускается с объяснением',
              'залито 2 из 2' in _why and 'столько YouTube принимает' in _why and 'без запроса' in _why, _why)
        app.yt_note_upload('R')
        g = app.yt_channel_gate('R', 1)
        check('YouTube принял больше выученного — лимит забыт, канал открыт',
              g['ok'] and not g['learned'], str(g))
        # Счёт говорил «место есть», а YouTube отказал: наш счёт к нему не подходит — ждём всё окно.
        yt_reset(times={'V': [_now - 9 * H, _now - 8 * H, _now - 7 * H, _now - 6 * H]},
                 caps={'V': {'n': 10, 'at': _now - 20 * H}})
        check('с выученным лимитом 10 и четырьмя заливками канал открыт',
              app.yt_channel_gate('V', 3)['ok'] and app.yt_channel_gate('V', 3)['cap'] == 10)
        rec = app.yt_note_refusal('V')
        g = app.yt_channel_gate('V', 1)
        check('отказ при свободном месте: жёсткая пауза до суток от последней заливки, лимит не трогаем',
              rec.get('cap') == 10 and (not g['ok']) and g['why'] == 'refused'
              and abs(g['until'] - (_now + 18 * H)) < 5, '%s | %s' % (rec, g))
        yt_reset(times={'K': [_now - 3 * H]}, caps={'K': {'n': 2, 'at': _now - 80 * H}})
        check('выученный лимит старше трёх суток забывается', app.yt_channel_gate('K', 3)['cap'] == 15
              and app.yt_channel_gate('K', 3)['ok'])
        yt_reset(caps={'N': {'n': 2, 'at': _now - H}})
        check('набор крупнее лимита канала: пустой канал берём, занятый — нет',
              app.yt_channel_gate('N', 3)['ok'])
        yt_reset()
        r1 = app.yt_note_refusal('Z'); r2 = app.yt_note_refusal('Z')
        check('отказ при пустом окне: проба через 3 часа, при повторе — через 6',
              r1.get('n') == 0 and abs(r1['until'] - time.time() - 3 * H) < 10
              and abs(r2['until'] - time.time() - 6 * H) < 10, '%s | %s' % (r1, r2))
        check('пауза снимается руками', app.yt_unlock(ch_id='Z') and app.yt_channel_gate('Z', 1)['ok'])

        yt_reset()
        for _ in range(3):
            app.yt_note_call('pX')
        app.yt_note_quota('pX')
        pg = app.yt_project_gate('pX')
        check('квота проекта: запросы считаются, отказ закрывает проект до конца суток Google',
              pg['calls'] == 3 and (not pg['ok']) and pg['until'] == app._pt_day()[1], str(pg))
        check('канал закрытого проекта пропускается без запроса',
              'квота' in app.yt_skip_reason('any', {'name': 'x', 'project_id': 'pX'}, 1))
        app.yt_note_project_ok('pX')
        pg = app.yt_project_gate('pX')
        check('проект снова принял ролик — пауза снята, залитое посчитано',
              pg['ok'] and pg['done'] == 1, str(pg))
        import calendar as _cal
        _d, _e = app._pt_day(_cal.timegm((2026, 11, 25, 12, 0, 0)))
        check('сутки Google кончаются в полночь по Тихоокеанскому (зимой это 08:00 UTC)',
              _d == '2026-11-25' and _e == _cal.timegm((2026, 11, 26, 8, 0, 0)), '%s %s' % (_d, _e))
        _d, _e = app._pt_day(_cal.timegm((2026, 7, 1, 5, 0, 0)))
        check('летом сутки Google сдвинуты на час (07:00 UTC)',
              _d == '2026-06-30' and _e == _cal.timegm((2026, 7, 1, 7, 0, 0)), '%s %s' % (_d, _e))
        check('лимит YouTube и квота проекта не считаются поломкой канала',
              app.is_soft_refusal_text('дневной лимит загрузок YouTube исчерпан (сбросится через ~24ч)')
              and app.is_soft_refusal_text(app.friendly_upload_error(Exception('uploadLimitExceeded')))
              and app.is_soft_refusal_text(app.friendly_upload_error(_q429))
              and not app.is_soft_refusal_text('токен отозван — удали канал и добавь заново'))

        _jf = os.path.join(tmp, 'journal_boot.json')
        _jq.dump([{'channel': 'J1', 'user': 'pavel', 'ts': _now - 1 * H},
                  {'channel': 'J1', 'user': 'pavel', 'ts': str(_now - 30 * H)},
                  {'channel': 'J2', 'user': 'pavel', 'ts': _now - 50 * H},
                  {'channel': 'J3', 'user': 'pavel', 'ts': 0}], open(_jf, 'w'))
        app.JOURNAL_FILE = _jf
        os.remove(app.YT_STATE_FILE)
        st = app.yt_state_load()
        check('после обновления окно каналов поднимается из журнала заливок',
              len(st['times'].get('J1', [])) == 2 and 'J2' not in st['times'] and 'J3' not in st['times']
              and app.yt_channel_gate('J1', 1)['count'] == 1 and os.path.exists(app.YT_STATE_FILE),
              str(st['times']))

        # Сценарий целиком, на настоящих счётчиках: канал A забит за сутки,
        # каналу B YouTube откажет, канал C свободен.
        app.UPLOADS_TODAY_FILE = os.path.join(tmp, 'uploads_today.json')
        for _n in ('bump_upload_count', 'increment_project_upload',
                   'load_uploads_today', 'save_uploads_today'):
            setattr(app, _n, _psaved[_n])
        _lim = _refuse(400, 'uploadLimitExceeded',
                       'The user has exceeded the number of videos they may upload.')
        _tried2, _saved2 = [], {}
        class FRL:
            def __init__(s, tok): s.tok = tok
            def next_chunk(s, num_retries=0):
                _tried2.append(s.tok)
                if s.tok == 'tB':
                    raise _lim
                return (None, {'id': 'vid_%s_%d' % (s.tok, len(_tried2))})
        app.get_youtube_service = lambda token_file=None, proxy='': type('Y', (), {
            'videos': lambda s: type('V', (), {'insert': lambda s2, **kw: FRL(token_file)})()})()
        app.save_channels = lambda u, d: _saved2.update(d)
        yt_reset(times={'A': [time.time() - 20 * H + i * 60 for i in range(15)],
                        'B': [time.time() - 6 * H + i * 60 for i in range(10)]})

        def _run(jid):
            app.MASS_UPLOAD_JOBS[jid] = {'status': 'pending', 'log': [], 'sets': [], 'total': 0, 'done': 0}
            app.auto_convert_and_upload(jid, vid, 1, 'C', 'unlisted', 'pavel',
                                        custom_title='T', custom_desc='D', as_is=True)
            return app.MASS_UPLOAD_JOBS[jid]
        j1 = _run('st_win1')
        check('забитый за сутки канал пропущен без запроса, отказ получил только B',
              _tried2 == ['tB', 'tC'], 'обращались к: %s | %s' % (_tried2, j1['log']))
        check('в журнале сказано, почему пропущен A и когда YouTube откроет B',
              any('Канал A' in l and 'за последние 24 часа залито 15 из 15' in l for l in j1['log'])
              and any('YouTube закрыл канал B' in l and 'принимает 10 за 24 часа' in l
                      and 'место освободится' in l for l in j1['log']), str(j1['log']))
        check('лимит YouTube не записан каналу как ошибка',
              not _saved2.get('B', {}).get('last_error'), str(_saved2.get('B')))
        del _tried2[:]
        j2 = _run('st_win2')
        check('второй запуск: в закрытые каналы панель больше не стучится',
              _tried2 == ['tC'] and [x['channel'] for x in j2['sets']] == ['C'],
              'обращались к: %s | %s' % (_tried2, j2['log']))
        p1, p2 = app.yt_project_gate('p1'), app.yt_project_gate('p2')
        check('запросы посчитаны по проектам, отказанный тоже в счёте',
              p1['calls'] == 1 and p1['done'] == 0 and p2['calls'] == 2 and p2['done'] == 2,
              '%s | %s' % (p1, p2))
        check('окно канала C выросло на залитое', app.yt_channel_gate('C', 1)['count'] == 2)

        # Политика на дистанции: три дня байер каждые 20 минут с 10 до 20 пробует
        # залить набор из трёх на один канал. Считаем принятые и отказанные запросы
        # при трёх устройствах YouTube: лимита не видно; лимит 10 в скользящем окне;
        # лимит 10 с блокировкой на сутки от последней заливки.
        _rt = app.time
        _clock = [time.time()]

        class _FakeTime:
            def __getattr__(s, k): return getattr(_rt, k)
            def time(s): return _clock[0]

        def _simulate(limit, lockout, days=3):
            yt_reset()
            accepted, locked = [], [0.0]
            ok = bad = 0
            start = _clock[0]
            for step in range(days * 72):
                _clock[0] = start + step * 1200
                if not (10 <= (step * 20 // 60) % 24 < 20):
                    continue
                if app.yt_skip_reason('S', {'name': 'S'}, 3):
                    continue
                for _f in range(3):
                    live = [t for t in accepted if _clock[0] - t < 86400]
                    if len(live) >= limit or _clock[0] < locked[0]:
                        if lockout and len(live) >= limit:
                            locked[0] = max(live) + 86400
                        app.yt_note_refusal('S'); bad += 1
                        break
                    accepted.append(_clock[0]); app.yt_note_upload('S'); ok += 1
                    _clock[0] += 5
            return ok, bad
        app.time = _FakeTime()
        try:
            _full, _roll, _lock = _simulate(100, False), _simulate(10, False), _simulate(10, True)
        finally:
            app.time = _rt
        check('три дня, YouTube не отказывает: 15 в сутки и ни одного отказанного запроса',
              _full[1] == 0 and _full[0] >= 39, 'принято %d, отказано %d' % _full)
        check('три дня, лимит канала 10: один отказ на всё время, канал работает на свои 10 в сутки',
              _roll[1] <= 1 and _roll[0] >= 25, 'принято %d, отказано %d' % _roll)
        check('три дня, лимит 10 с суточной блокировкой: отказов не больше двух в день',
              _lock[1] <= 6 and _lock[0] >= 25, 'принято %d, отказано %d' % _lock)
        print('     (дистанция: без отказов %s · лимит 10 %s · лимит 10 с блокировкой %s — принято/отказано)'
              % ('%d/%d' % _full, '%d/%d' % _roll, '%d/%d' % _lock))

        # Массовая дорога: отказ ловится общим except — память должна работать и там.
        yt_reset()
        _chq.pop('A')
        _files = [{'path': vid, 'fmt': '9:16'}]

        def _runm(jid):
            app.MASS_UPLOAD_JOBS[jid] = {'status': 'pending', 'log': [], 'sets': [], 'total': 0, 'done': 0}
            app.mass_upload_to_youtube(jid, _files, 1, 'T', 'D', 'unlisted', 'pavel')
            return app.MASS_UPLOAD_JOBS[jid]
        del _tried2[:]
        _runm('st_m1'); _t1 = list(_tried2); del _tried2[:]
        m2 = _runm('st_m2')
        check('массовая заливка: отказ запомнен, второй запуск идёт мимо закрытого канала',
              _t1 == ['tB', 'tC'] and _tried2 == ['tC'], '%s | %s | %s' % (_t1, _tried2, m2['log']))

        # «Готовые ролики» — третья дорога, тот же общий except.
        yt_reset()

        def _runr(jid):
            app.MASS_UPLOAD_JOBS[jid] = {'status': 'pending', 'log': [], 'sets': [], 'total': 0, 'done': 0}
            app.ready_upload_to_youtube(jid, [{'path': vid, 'fmt': '9:16'}], 1, 'C', 'unlisted',
                                        'pavel', custom_title='T', custom_desc='D')
            return app.MASS_UPLOAD_JOBS[jid]
        del _tried2[:]
        _runr('st_r1'); _t1 = list(_tried2); del _tried2[:]
        r2 = _runr('st_r2')
        check('готовые ролики: отказ запомнен, второй запуск идёт мимо закрытого канала',
              _t1 == ['tB', 'tC'] and _tried2 == ['tC'], '%s | %s | %s' % (_t1, _tried2, r2['log']))

        # Проект с закрытой квотой снимается одной строкой, а не строкой на канал.
        yt_reset()
        app.yt_note_quota('p1')
        del _tried2[:]
        j3 = _run('st_q1')
        check('закрытый проект: одна строка в журнале и ни одного запроса к его каналам',
              _tried2 == ['tC']
              and sum('Проект «' in l and 'квота Google исчерпана' in l for l in j3['log']) == 1,
              '%s | %s' % (_tried2, j3['log']))

        yt_reset(times={'B': [time.time() - H] * 15})
        check('«Авто» одиночной заливки берёт канал, который YouTube примет',
              app.get_best_channel('pavel')[0] == 'C')
        yt_reset(times={'B': [time.time() - H] * 15, 'C': [time.time() - 2 * H] * 15})
        del _tried2[:]
        app.UPLOAD_JOBS['st_single'] = {'status': 'pending', 'log': [], 'links': []}
        app.upload_to_youtube('st_single', [{'path': vid, 'fmt': '9:16', 'size': 1}],
                              'T', 'D', 'unlisted', 'auto', 'pavel')
        _sl = app.UPLOAD_JOBS['st_single']
        check('одиночная заливка: все каналы закрыты — честный отказ со временем, без запросов',
              _sl['status'] == 'error' and not _tried2
              and any('не принимает ни на один канал' in l and 'откроется' in l for l in _sl['log']),
              str(_sl['log']))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for _n, _f in _psaved.items():
            setattr(app, _n, _f)

    print('\n7. Счётчики загрузок: без гонок и не боятся битого файла')
    # Практика: файл счётчиков общий на всех байеров, заливки идут в потоках.
    # Раньше словарь читался один раз и сохранялся целиком -> параллельные
    # прогоны затирали инкременты, канал уходил за MAX_CH_PER_DAY и ловил
    # реальный лимит YouTube. Плюс прерванная запись оставляла битый JSON.
    import threading as _th, json as _js
    _tf = tempfile.NamedTemporaryFile(suffix='.json', delete=False); _tf.close()
    _orig_file = app.UPLOADS_TODAY_FILE
    app.UPLOADS_TODAY_FILE = _tf.name
    try:
        check('пустой файл счётчиков не роняет', isinstance(app.load_uploads_today(), dict))
        open(_tf.name, 'w').write('{битый')
        check('битый файл счётчиков не роняет', isinstance(app.load_uploads_today(), dict))
        os.remove(_tf.name)
        N, PER = 8, 25
        def _w():
            for _ in range(PER):
                app.bump_upload_count('chTest')
        ts = [_th.Thread(target=_w) for _ in range(N)]
        [t.start() for t in ts]; [t.join() for t in ts]
        got = _js.load(open(_tf.name))['counts']['chTest']
        check('%d потоков × %d инкрементов — ничего не потеряно' % (N, PER), got == N * PER,
              'получили %d вместо %d' % (got, N * PER))
    finally:
        app.UPLOADS_TODAY_FILE = _orig_file
        for f in (_tf.name, _tf.name + '.tmp'):
            if os.path.exists(f):
                os.remove(f)

    print('\n8. Битые файлы данных не убивают панель')
    # Панель убивают при каждом обновлении. Раньше запись шла на месте, и
    # обрезанный channels_*.json стоил бы байеру ВСЕХ каналов.
    _d = tempfile.mkdtemp(prefix='vejson_')
    _origf = app.get_channels_file
    try:
        app.get_channels_file = lambda u: os.path.join(_d, 'channels_%s.json' % u)
        app.save_channels('t', {'ch1': {'name': 'Канал 1'}})
        check('обычное чтение каналов', app.load_channels('t').get('ch1', {}).get('name') == 'Канал 1')
        pth = app.get_channels_file('t')
        open(pth, 'w').write('{"ch1": {"name": "Кана')     # запись оборвана
        check('битый файл каналов не роняет', isinstance(app.load_channels('t'), dict))
        check('битый файл сохранён как .corrupt', os.path.exists(pth + '.corrupt'))
        open(pth, 'w').write('')
        check('пустой файл каналов не роняет', app.load_channels('t') == {})
        app.save_channels('t', {'a': {'name': 'A'}})
        check('после сбоя каналы снова пишутся', app.load_channels('t').get('a', {}).get('name') == 'A')
    finally:
        app.get_channels_file = _origf
        shutil.rmtree(_d, ignore_errors=True)

    print('\n9. Понятные тексты ошибок')
    fe = app.friendly_upload_error
    # Сетевая ошибка НЕ должна утверждать, кто виноват: в эту же ветку падает и
    # мёртвый прокси, и заблокированный Google, и сбой у самого провайдера.
    # Раньше текст гласил «прокси не отвечает (токен живой)» — байер чинил живой
    # прокси, пока настоящая причина была в другом (Вика, 19.08).
    _net = fe(Exception("SOCKSHTTPSConnectionPool ... Max retries exceeded"))
    check('сетевая ошибка отправляет к проверке, а не обвиняет прокси',
          'Проверить каналы' in _net)
    check('сетевая ошибка не врёт про живой токен', 'токен живой' not in _net)
    check('Failed to parse -> про формат', 'формат' in fe(Exception("Failed to parse: 1.2.3.4:80:u:p")))
    check('invalid_grant -> про токен', 'токен' in fe(Exception("invalid_grant: Token has been expired")))
    check('uploadLimitExceeded -> про лимит', 'лимит' in fe(Exception("uploadLimitExceeded")))

    print('\n10. Домен не захардкожен в генерации ТЗ')
    src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
    bad_lines = [l.strip()[:90] for l in src.splitlines()
                 if 'gvita.beauty' in l and 'landers/official-${' in l]
    check('нет хардкода домена в шаблонах URL', not bad_lines, '; '.join(bad_lines))

    print('\n' + '=' * 52)
    print('Пройдено: %d   Провалено: %d' % (len(OK), len(FAIL)))
    if FAIL:
        print('\nПровалились:')
        for f in FAIL:
            print('  ✕ ' + f)
        return 1
    print('Всё зелёное 🎉')
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(); sys.exit(1)
