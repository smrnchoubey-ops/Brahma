import base64
import json
import zlib
import re
import os

def encode_mermaid(graph):
    # mermaid.ink expects a base64 encoded JSON string:
    # {"code":"...","mermaid":"{\"theme\":\"default\"}"}
    j = json.dumps({
        "code": graph,
        "mermaid": {"theme": "default"}
    })
    # Deflate and base64 encode
    compressed = zlib.compress(j.encode('utf-8'))
    # Wait, the v3 of mermaid.ink supports just base64 encoding the state object, but the simplest way is pako deflate -> base64, OR just base64 encoding JSON string for the newer API.
    # Actually, the simplest is base64 of the string! https://mermaid.ink/img/pako:... or https://mermaid.ink/img/base64:...
    # The base64 URL is just the base64 encoded string of the graph!
    b64 = base64.urlsafe_b64encode(graph.encode('utf-8')).decode('utf-8')
    return f"https://mermaid.ink/img/{b64}"

with open(r'C:\Users\Kshama\.gemini\antigravity-ide\brain\9509e366-ed83-4a4a-ad5e-ca2bb44604be\BRAHMA_COS_MEETING_REVIEW_DOC.md', 'r', encoding='utf-8') as f:
    content = f.read()

# Prepend the meeting intro
intro = """# MANDATORY TEAM MEETING: BRAHMA COS AUDIT & REVIEW
**Date:** Monday, 6:00 PM
**Location:** Online Meeting (Link to be shared prior to the meeting)
**Attendance:** Mandatory

---
### Notice to All Team Members
This is to inform everyone that an online team meeting will be held on Monday at 6:00 PM. Attendance is mandatory for all team members, and everyone is expected to join the meeting on time.

Please make sure you come fully prepared with an understanding of your assigned responsibilities, current progress, pending tasks, and any issues or concerns related to your respective work. We will be reviewing the responsibilities and overall progress of the team during the meeting, so please ensure that you are well-prepared.

I expect everyone to treat this meeting with the required priority and professionalism. Be punctual and ensure your availability at 6:00 PM sharp.

*Please see the comprehensive codebase audit and status report below, which will serve as the agenda for our review.*

---

"""

# Regex to find mermaid blocks and replace with image links
def replacer(match):
    code = match.group(1).strip()
    img_url = encode_mermaid(code)
    return f"![Architecture Diagram]({img_url})"

new_content = intro + re.sub(r'```mermaid\n(.*?)\n```', replacer, content, flags=re.DOTALL)

with open(r'C:\Users\Kshama\.gemini\antigravity-ide\brain\9509e366-ed83-4a4a-ad5e-ca2bb44604be\MEETING_AGENDA_AND_REPORT.md', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Created MEETING_AGENDA_AND_REPORT.md with embedded images.")
