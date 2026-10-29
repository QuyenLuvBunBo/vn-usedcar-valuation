"""Source URL scope and robots rules."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
BASE = "https://xe.chotot.com"

class Robots:
    """Small robots matcher supporting * and $, longest rule and Allow ties.

    urllib.robotparser does not implement Google's wildcard matching, so do not
    use it for Chotot's /*page= rules. Rules are matched case-sensitively.
    """
    def __init__(self,text,agent='DSCourseCrawler'):
        groups=[]; agents=[]; rules=[]; delay=0; directives=False
        for line in text.splitlines()+['User-agent: __end__']:
            line=line.split('#',1)[0].strip()
            if ':' not in line: continue
            key,value=(p.strip() for p in line.split(':',1)); key=key.lower()
            if key=='user-agent':
                if directives:
                    groups.append((agents,rules,delay)); agents=[]; rules=[]; delay=0; directives=False
                agents.append(value.lower())
            elif key in ('allow','disallow') and agents:
                directives=True
                if value: rules.append((key=='allow',value))
            elif key=='crawl-delay' and agents:
                directives=True
                try: delay=float(value)
                except ValueError: pass
        matches=[g for g in groups if any(a=='*' or a in agent.lower() for a in g[0])]
        specific=[g for g in matches if any(a!='*' and a in agent.lower() for a in g[0])]
        if specific:
            size=max(len(a) for g in specific for a in g[0] if a in agent.lower())
            matches=[g for g in specific if any(len(a)==size and a in agent.lower() for a in g[0])]
        self.rules=[r for g in matches for r in g[1]]
        self.delay=max((g[2] for g in matches),default=0)

    def allowed(self,url):
        u=urlsplit(url); path=u.path+('?' + u.query if u.query else '')
        hits=[]
        for allow,pattern in self.rules:
            ending=pattern.endswith('$'); p=pattern[:-1] if ending else pattern
            regex='^'+re.escape(p).replace(r'\*','.*')+('$' if ending else '')
            if re.search(regex,path): hits.append((len(p.replace('*','')),allow))
        return max(hits)[1] if hits else True

def canonical(url):
    u=urlsplit(urljoin(BASE,url))
    if u.scheme!='https' or u.netloc!='xe.chotot.com' or not u.path.startswith('/mua-ban-oto'):
        return None
    return urlunsplit((u.scheme,u.netloc,u.path,u.query,''))

