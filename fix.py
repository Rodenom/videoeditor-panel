
lines=open('/Users/macbookair/Desktop/VideoEditor/app.py').readlines()
for i,l in enumerate(lines):
    if "if(l.match(/^#?" in l and 'TITLES' in l:
        lines[i]="    if(l.match(/^#{0,2}\\s*TITLES?:/i)||l.match(/^#{0,2}\\s*ЗАГОЛОВКИ/i)){mode='t';return;}\n"
        print(f'OK titles {i+1}')
    if "if(l.match(/^#?" in l and 'DESCS' in l:
        lines[i]="    if(l.match(/^#{0,2}\\s*DESCS?:/i)||l.match(/^#{0,2}\\s*ОПИСАНИЯ/i)){mode='d';return;}\n"
        print(f'OK descs {i+1}')
open('/Users/macbookair/Desktop/VideoEditor/app.py','w').writelines(lines)
