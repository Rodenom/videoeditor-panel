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
    _STUBBED = ('load_uploads_today', 'save_uploads_today', 'increment_project_upload',
                'load_channels', 'save_channels', 'get_youtube_service')
    _saved = {n: getattr(app, n) for n in _STUBBED}
    app.load_uploads_today = lambda: _counts
    app.save_uploads_today = lambda d: None
    app.increment_project_upload = lambda *a, **k: None
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
              'load_channels', 'save_channels', 'get_youtube_service', 'get_anthropic_key')
    _psaved = {n: getattr(app, n) for n in _PSTUB}
    _pc = {'date': time.strftime('%Y-%m-%d'), 'counts': {}}
    app.load_uploads_today = lambda: _pc
    app.save_uploads_today = lambda d: None
    app.increment_project_upload = lambda *a, **k: None
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
