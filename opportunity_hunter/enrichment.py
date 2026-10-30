"""Evidence-based presentation shared by audits and legacy-record exports."""
import re
from urllib.parse import unquote

EXTRA_FIELDS=['maps_url','google_category','google_rating','google_review_count','maps_checked_at','public_emails','email_sources','email_verification_status']
BASE_FIELDS=['id','name','city','industry','website','public_contacts','contact_source','website_findings','evidence_urls','verification_date','score','qualification_status','suggested_solution','outreach_angle','outreach_status','follow_up_date','next_action','last_researched']
FIELDS=BASE_FIELDS+EXTRA_FIELDS
INDUSTRIES=[('Electrical contractor',r'\belectric(?:al|ian|ians)\b'),('Plumbing',r'\bplumb(?:er|ers|ing)\b'),('Heating and cooling',r'\bhvac\b|\bheating\b|\bair conditioning\b'),('Auto repair',r'\bauto(?:motive)? repair\b|\bcar repair\b|\bmechanic\b'),('Tree care',r'\btree (?:care|service|removal|trimming)\b|\barborist\b'),('Landscaping',r'\blandscap(?:e|er|ing)\b'),('Roofing',r'\broof(?:er|ing)\b'),('Cleaning',r'\bcleaning service\b|\bhouse cleaning\b')]


def valid_email(value):
    value=unquote(value).strip().lower()
    if not re.fullmatch(r'[a-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}',value):return False
    local,host=value.rsplit('@',1)
    return not (host.endswith(('.png','.jpg','.jpeg','.gif','.webp','.svg','.woff','.css','.js','.example','.invalid','.test')) or host in ('example.com','example.org','example.net','domain.com','email.com','sentry.io') or host.endswith('.sentry.io') or local in ('yourname','youremail','example','test') or '..' in value)


def classify(p,text):
    matches=[label for label,pattern in INDUSTRIES if re.search(pattern,text,re.I)]
    category=p.get('google_category','')
    mapped=next((label for label,pattern in INDUSTRIES if re.search(pattern,category,re.I)),None)
    if len(matches)==1:
        p['industry']=matches[0]
        if mapped and mapped!=matches[0]:p.setdefault('unverified',[]).append('Industry conflict: Maps category differs from website services; review required')
    elif len(matches)>1:
        p['industry']=mapped if mapped in matches else ' / '.join(matches)
        p.setdefault('unverified',[]).append('Multiple website service categories; confirm primary industry')
    elif category:
        p['industry']=category+' (Maps category; website confirmation pending)'
    elif not p.get('industry') or 'verify' in p['industry']:
        p['industry']='Unknown — verify website services'


def outreach_angle(p):
    issue=next((f for f in p.get('findings',[]) if f.get('verified') and f.get('severity')=='important'),None)
    if not issue:return 'Research only: verify a meaningful issue before drafting outreach.'
    angles={'mobile_scaled_text':'Would you be open to a free look at making your service details and contact options easier to read on a phone?',
            'mobile_overflow':'Would a free look at making your service and contact pages fit a phone screen be useful?',
            'low_text_contrast':'Would you be open to a free look at making your service and contact information easier to read?',
            'unlabeled_form':'Would a free look at making the inquiry form easier to use with assistive technology be useful?'}
    opener=angles.get(issue.get('code'),'Would you be open to reviewing this observed website issue together?')
    return f"{p['name']}: {issue['observation']} {opener}"


def readable_findings(p):
    seen=set();items=[]
    for f in p.get('findings',[]):
        if not f.get('verified') or f.get('code') in seen:continue
        seen.add(f.get('code'));items.append(f["observation"]+' Why it matters: '+f['impact']+' Evidence: '+f['url']+'; checked '+f['checked_at'])
    return '\n\n'.join(items) or 'No verified meaningful website finding; further research required.'


def email_fields(p):
    contacts=[c for c in p.get('contacts',[]) if c['kind']=='email' and valid_email(c['value'])]
    return {'public_emails':'; '.join(dict.fromkeys(c['value'].lower() for c in contacts)),
            'email_sources':'; '.join(dict.fromkeys(c['source'] for c in contacts)),
            'email_verification_status':'Published on official website; deliverability and recipient role unverified' if contacts else 'Unknown — no public email verified'}
