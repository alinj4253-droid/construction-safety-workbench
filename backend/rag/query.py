from __future__ import annotations
import re

TOPICS=(
    ('stairs','楼梯口防护',('楼梯口','楼梯平台','梯段边','楼梯防护'),('楼梯','防护栏杆'),(('楼梯','梯段'),)),
    ('edge','临边防护',('临边','基坑边','基坑护栏','临边护栏','防护栏杆','栏杆','挡脚板','横杆','立杆间距'),('临边','防护栏杆'),(('临边','防护栏杆','临空','边沿','周边','基坑'),('防护','栏杆','围护'))),
    ('electric','施工临时用电',('临时用电','临电','接地','接零','TN-S','TN系统','保护接地导体','配电','电源中性点'),('临时用电','接地','配电'),(('用电','接地','接零','配电','TN-S','TN系统'),)),
    ('scaffold','脚手架',('脚手架','连墙件','架体'),('脚手架',),(('脚手架','连墙件','架体'),)),
    ('helmet','安全帽佩戴',('安全帽','劳动防护用品'),('安全帽','劳动防护用品'),(('安全帽','劳动防护用品'),)),
    ('space','有限空间作业',('有限空间','受限空间'),('有限空间',),(('有限空间','受限空间'),)),
    ('formwork','模板工程',('模板','支模'),('模板',),(('模板','支模'),)),
    ('lifting','起重机械',('起重','吊装','塔吊'),('起重','吊装'),(('起重','吊装','塔吊'),)),
    ('height','高处作业',('高处作业','高空作业'),('高处','防护'),(('高处','高空'),)),
)
REFERENCES=re.compile(r'这个|这种|上述|刚才|前面|这类|那类|那种|那个|它|该防护|该措施|此类')
FILLERS=(
    '常见的不规范情况','常见不规范情况','常见的隐患','常见隐患','不规范情况','检查事项','检查项目','检查要点','检查清单',
    '主要隐患','隐患有哪些','安全隐患','风险隐患','隐患','有什么要求','有哪些要求','有什么规定','有哪些规定','具体要求',
    '的设置要求','有哪些','有什么','是什么','怎么样','如何','怎么','为何','为什么','要求','规定','规范','标准','条款','原文',
    '常见','高频','情况','问题','哪些','什么','多少','是否','可以','应该','应当','进行','关于','相关','请问','请教','麻烦',
    '能不能','能否','帮我','给我们','给我','说一下','说说','介绍一下','详细说明','详细','一下','工地上','施工现场','现场','工地','施工',
    '刚才说的','刚才提到的','前面说的','你说的','所说的','提到的','前述','刚说的','上述','这个','这种','这类','那种','那个','它的','它','这项','这些','那些','那个',
    '关注点','检查点','薄弱环节','关注','需要注意','需要','检查','核查','排查','验收','缺陷','具体','不规范','不合规','违章','风险','继续','再解释','再说','进一步','还有','除此之外',
    '我们','咱们','那么','列出','归纳','概括','总结','说明','解释','介绍','讲讲','留意','考虑',
)
META=re.compile(r'^(?:(?:谢谢你?|多谢了?|好的|明白了?|知道了|了解了|收到)[，,。.!！\s]*)+$')
STANDARD=re.compile(r'(?:JGJ\s*/?\s*T?|GB\s*/?\s*T?|DBJ\s*/?\s*T?)\s*\d+(?:\s*[-/—－–]\s*\d+)+',re.I)
GENERIC=re.compile(r'防护|措施|设施|对象|事情|东西|做法|项目|细节|情况|部位|环节|建议|作业|方面|部分|数值|尺寸|高度|间距|数量|位置|构造|检查|重点|要点|事故|注意|统计|占比|有|还|再|为|的|要|需|应|能|可|该|也|和|与|些|点|呢|吗|何|了|你|我|他|她|们|说|讲|谈|时|去|来|请|给|帮|让')

def memory_intent(text):
    if text.startswith(('记住','请记住')):return 'remember'
    if any(word in text for word in ('你记得我','记住了什么','我的项目背景')):return 'recall'
    return None

def normalize_query(text):
    text=re.sub(r'(?i)\btn\s*[-－—]\s*s\b','TN-S',text).replace('临电','临时用电').replace('基坑边','基坑临边')
    text=STANDARD.sub(' ',text)
    text=re.sub(r'第?\d+\.\d+\.\d+条?',' ',text)
    for word in sorted(set(FILLERS),key=lambda word:(-len(word),word)):text=text.replace(word,' ')
    text=REFERENCES.sub(' ',text)
    text=re.sub(r'^[那这]\s*|[的呢吗啊？?。！!]+$',' ',text)
    return ' '.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9/-]+',text)).strip()

def intent_for(text):
    if any(x in text for x in ('统计','占比','发生率','频率','高频','最常见','最多')):return 'statistics'
    if any(x in text for x in ('隐患','不规范','不合规','检查','核查','排查','缺陷','违规','违章','风险点','验收','注意事项','薄弱环节')):return 'checks'
    if any(x in text for x in ('为什么','为何','原因','原理')):return 'explanation'
    if '核心要求' in text:return 'overview'
    return 'requirements'

def describe(text):
    focus=re.split(r'换个话题|换成|改问|转到|现在(?:想|要)?问|不谈.+?而是',text)[-1]
    found=[]
    for kind,subject,aliases,terms,groups in TOPICS:
        if not any(a.lower() in focus.lower() for a in aliases):continue
        if kind=='edge' and any(w in focus for w in ('脚手架','连墙件','架体')) and not any(w in focus for w in ('临边','栏杆','基坑')):continue
        if kind=='edge' and any(t['kind']=='stairs' for t in found) and '临边' not in focus and '基坑' not in focus:continue
        if kind=='height' and any(t['kind'] in {'edge','stairs'} for t in found):continue
        if kind=='edge' and '基坑' in focus:subject='基坑临边防护'
        if kind=='electric' and any(w in focus.lower() for w in ('接地','接零','tn-s','保护接地')):
            subject='施工临时用电接地';terms=('临时用电','接地','保护接地导体');groups=(('接地','接零','TN-S','TN系统'),)
        facets=tuple(w for w in ('连墙件','三级配电','立杆','横杆','挡脚板') if w in focus)
        if facets:
            terms=(*terms,*facets)
            for facet in facets:
                if facet in {'连墙件','三级配电'}:groups=(*groups,(facet,))
        found.append({'kind':kind,'subject':subject,'terms':terms,'groups':groups,'facet':facets[0] if facets else '','facets':facets})
    return found

def analyze_query(question):
    topics=describe(question)
    cleaned=normalize_query(question)
    selected=topics[0] if len(topics)==1 else {'kind':'unknown','subject':cleaned,'terms':tuple(cleaned.split()),'groups':(),'facet':'','facets':()}
    return {**selected,'question':question,'query':' '.join(dict.fromkeys(selected['terms'])),'intent':intent_for(question),'standard_numbers':STANDARD.findall(question),'ambiguous':len(topics)>1,'subjects':[t['subject'] for t in topics],'needs_clarification':False}

def resolve_query(question,history=()):
    state=None
    messages=[m for m in history if m.get('role')=='user']+[{'role':'user','content':question}]
    for message in messages:
        text=message['content'].strip();current=analyze_query(text)
        if memory_intent(text) or META.match(text):continue
        if current['ambiguous']:
            state={**current,'needs_clarification':True,'reason':'当前问题涉及多个对象，请明确要继续讨论哪一个：'+'、'.join(current['subjects'])+'。'}
        elif current['kind']!='unknown':
            component=current['kind']=='edge' and current['facets'] and not any(w in text for w in ('基坑','临边','栏杆','脚手架'))
            if component and state and not state['needs_clarification'] and state['kind'] in {'edge','scaffold'}:
                terms=tuple(dict.fromkeys((*state['terms'],*current['facets'])))
                state={**state,'question':text,'terms':terms,'query':' '.join(terms),'facet':current['facet'],'facets':current['facets'],'intent':current['intent']}
            else:state={**current,'context_message_id':message.get('id')}
        elif current['standard_numbers'] or GENERIC.sub('',current['subject']).strip():
            state={**current,'context_message_id':message.get('id')}
        elif state:state={**state,'question':text,'intent':current['intent']}
    if state:return {**state,'question':question,'intent':intent_for(question)}
    return {**analyze_query(question),'needs_clarification':True,'reason':'当前会话中还不能确定“这个/这种”指的具体对象。请说明作业类型或防护设施，例如临边栏杆、楼梯口防护或临时用电接地。'}
