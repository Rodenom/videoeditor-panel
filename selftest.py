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
            ('ready_upload', app.ready_upload_to_youtube, dict(custom_title='T', custom_desc='D')),
            ('mass_upload', app.mass_upload_to_youtube, None),
        ]:
            cap = []
            class FR:
                def __init__(s, p, t): cap.append((hashlib.md5(open(p, 'rb').read()).hexdigest()[:10], t)); s._i = 'v%d' % len(cap)
                def next_chunk(s): return (None, {'id': s._i})
            class FV:
                def insert(s, part, body, media_body): return FR(media_body._p, body['snippet']['title'])
            app.get_youtube_service = lambda token_file=None, proxy='': type('Y', (), {'videos': lambda s: FV()})()
            jid = 'st_' + mode_name
            app.MASS_UPLOAD_JOBS[jid] = {'status': 'pending', 'log': [], 'sets': [], 'total': 0, 'done': 0}
            try:
                if kwargs is not None:
                    fn(jid, files, 2, 'Cat', 'unlisted', 'pavel', **kwargs)
                else:
                    fn(jid, files, 2, 'T', 'D', 'unlisted', 'pavel')
                check('%s: 4 файла уникальны' % mode_name, len(set(h for h, _ in cap)) == 4, '%d уник.' % len(set(h for h, _ in cap)))
                check('%s: 4 заголовка уникальны' % mode_name, len(set(t for _, t in cap)) == 4)
                left = [f for f in os.listdir(app.OUTPUT_DIR) if f.startswith('uq_' + jid)]
                check('%s: временные файлы почищены' % mode_name, not left)
            except Exception as e:
                check('%s отработал' % mode_name, False, str(e)[:140])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('\n6. Понятные тексты ошибок')
    fe = app.friendly_upload_error
    check('SOCKS -> «прокси не отвечает»', 'прокси не отвечает' in fe(Exception("SOCKSHTTPSConnectionPool ... Max retries exceeded")))
    check('Failed to parse -> про формат', 'формат' in fe(Exception("Failed to parse: 1.2.3.4:80:u:p")))
    check('invalid_grant -> про токен', 'токен' in fe(Exception("invalid_grant: Token has been expired")))
    check('uploadLimitExceeded -> про лимит', 'лимит' in fe(Exception("uploadLimitExceeded")))

    print('\n7. Домен не захардкожен в генерации ТЗ')
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
