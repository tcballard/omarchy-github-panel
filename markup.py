"""Small escaped Markdown renderer. Remote HTML is always literal text."""
import html
import re
from urllib.parse import urljoin, urlparse
from navigation import web_url


def render(source, base=''):
    # Deliberately limited to common prose/code, never a general HTML engine.
    images = []
    def inline(text):
        tokens = []
        def token(value):
            tokens.append(value)
            return '\x01' + str(len(tokens)-1) + '\x02'
        def link(m):
            image, label, url = m.groups()
            url = urljoin(base, html.unescape(url))
            if not web_url(url):
                return label
            if image:
                if url.startswith('https://github.com/') and '/blob/' in url:
                    url=url.replace('https://github.com/','https://raw.githubusercontent.com/',1).replace('/blob/','/',1)
                images.append({'label':label or 'Image', 'url':url})
                return token('<i>[Image: ' + html.escape(label or 'Image') + ' — use Load image below]</i>')
            return token('<a href="' + html.escape(url, quote=True) + '">' + html.escape(label) + '</a>')
        text = re.sub(r'(!?)\[([^\]\n]*)\]\(([^\s)]+)\)', link, text)
        text = re.sub(r'`([^`\n]+)`', lambda m:token('<code>'+html.escape(m[1])+'</code>'), text)
        parts=urlparse(base).path.strip('/').split('/')
        if len(parts)>=2:
            repo='/'.join(parts[:2])
            text=re.sub(r'(?<![\w/])(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#([1-9][0-9]*)\b',
                lambda m:token('<a href="https://github.com/'+html.escape(m[1] or repo,quote=True)+'/issues/'+m[2]+'">'+html.escape(m[0])+'</a>'),text)
        text = html.escape(text)
        text = re.sub(r'\*\*([^*\n]+)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<i>\1</i>', text)
        # Autolink only safe HTTPS URLs. Attribute context cannot appear here.
        text = re.sub(r'https://[^\s<>]+', lambda m:token('<a href="'+html.escape(html.unescape(m[0]),quote=True)+'">'+m[0]+'</a>') if web_url(html.unescape(m[0])) else m[0], text)
        for i, value in reversed(list(enumerate(tokens))):
            text = text.replace('\x01'+str(i)+'\x02', value)
        return text
    out, code, fenced = [], [], False
    lines=str(source or '').replace('\x01','').replace('\x02','').splitlines()
    skip_until=-1
    for index,line in enumerate(lines):
        if index<skip_until: continue
        if not fenced and index+1<len(lines) and '|' in line:
            separators=lines[index+1].strip().strip('|').split('|')
            if len(separators)>1 and all(re.fullmatch(r'\s*:?-{3,}:?\s*',cell) for cell in separators):
                cells=lambda row:row.strip().strip('|').split('|')
                rows=['<tr>'+''.join('<th>'+inline(c.strip())+'</th>' for c in cells(line))+'</tr>']
                end=index+2
                while end<len(lines) and '|' in lines[end] and lines[end].strip():
                    rows.append('<tr>'+''.join('<td>'+inline(c.strip())+'</td>' for c in cells(lines[end]))+'</tr>');end+=1
                out.append('<table border="1" cellspacing="0" cellpadding="5">'+''.join(rows)+'</table>')
                skip_until=end
                continue
        if line.startswith('```'):
            if fenced:
                out.append('<pre>'+html.escape('\n'.join(code))+'</pre>'); code=[]
            fenced = not fenced
        elif fenced:
            code.append(line)
        elif re.match(r'^#{1,6} ',line):
            level = len(line.split(' ',1)[0]); out.append(f'<h{level}>'+inline(line[level+1:])+f'</h{level}>')
        elif line.startswith('> '):
            out.append('<blockquote>'+inline(line[2:])+'</blockquote>')
        elif re.match(r'^\s*[-*] ',line):
            out.append('<p>• '+inline(re.sub(r'^\s*[-*] ','',line))+'</p>')
        elif line.strip():
            out.append(inline(line)+'<br>')
        else:
            out.append('<br>')
    if code: out.append('<pre>'+html.escape('\n'.join(code))+'</pre>')
    return ''.join(out), images


def decorate(detail):
    repo = detail.get('target',{}).get('repo','')
    ref = detail.get('markdownRef','HEAD')
    filename=detail.get('target',{}).get('path','')
    directory=filename.rsplit('/',1)[0]+'/' if '/' in filename else ''
    base = f'https://github.com/{repo}/blob/{ref}/'+directory
    detail['richBody'], detail['images'] = render(detail.get('body',''), base)
    for tab in detail.get('tabs',[]):
        for block in tab.get('blocks',[]):
            if tab['id'] in ('conversation','release','overview','readme','reviews','threads','templates') or block.get('markdown'):
                block['richBody'], block['images'] = render(block.get('body',''),base)
    return detail
