try{ require('jsdom'); console.log('jsdom ok'); }catch(e){ console.log('NO jsdom:', e.code||e.message); }
console.log('resolve paths:', module.paths.slice(0,3).join(' | '));
