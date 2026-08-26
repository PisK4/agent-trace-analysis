from __future__ import annotations
from typing import Any
from .protocol_facts import PROTOCOL_FACTS_VERSION, select
def _wrap(family:str,summary:dict[str,Any])->dict[str,Any]:
    # Read the declared version rather than restating it. Two literals for one number
    # agreed for as long as both said 1, which is not a property a test can rely on.
    summary.setdefault('parser',{'family':family,'version':PROTOCOL_FACTS_VERSION,'error':summary.get('error')})
    return summary
def parse_request(path:str,headers:dict[str,str],body:bytes)->dict[str,Any]:
    adapter=select(path)
    try: result=adapter.parse_request(path,headers,body)
    except Exception as exc: result={'error':str(exc)}
    return _wrap(adapter.family,result)
def parse_response(path:str,headers:dict[str,str],content_type:str,body:bytes)->dict[str,Any]:
    adapter=select(path)
    try: result=adapter.parse_response(path,headers,content_type,body)
    except Exception as exc: result={'error':str(exc)}
    return _wrap(adapter.family,result)
