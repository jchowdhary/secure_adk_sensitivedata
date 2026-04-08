Why:

on_user_message_callback() in dlp_plugin.py (line 122) does not check should_scan_agent(...).
So the incoming user message is scanned once at entry, before agent filtering is applied.
That means sub-agents will usually receive the already-masked version of the original user input.
But agent filtering does apply later to:

before_model_callback() at dlp_plugin.py (line 144)
after_model_callback() at dlp_plugin.py (line 203)
before_tool_callback() at dlp_plugin.py (line 247)
after_tool_callback() at dlp_plugin.py (line 306)
And the filter itself is defined by should_scan_agent() in dlp_config.py (line 117).

So the practical answer is:

If your only goal is masking the original user prompt before it enters the system, then enabling just orchestrator is enough, because the user message gets masked at entry anyway.
If you also want protection for data created, retrieved, or echoed later by sub-agents, then you should still include those sub-agents in the allowlist or keep them out of the blocklist.
Examples where other agents still matter:

a sub-agent calls a tool that returns fresh PII
a sub-agent generates a response containing sensitive data
a sub-agent reformats or reconstructs data that was not in the original user text
a tool result contains unmasked values and only that sub-agent’s after_tool_callback() could catch it
So the clean conclusion is:

Initial ingress protection: yes, orchestrator alone is effectively enough.
End-to-end protection across delegation, tool use, and downstream outputs: no, you should still configure the other agents too.
One more nuance: your current code behavior is slightly stronger than the docs may imply, because user-message scanning is global and not agent-filtered. If you want, I can also review your DLP_README.md and DLP_SETUP_GUIDE.md wording and suggest a more precise explanation for that behavior.


what does scan user message paramater does .. does it filter the user prompt If yes then what is the difference between scan llm request .it will also be same ?


Yes, scan_user_messages filters the raw incoming user prompt.

The difference is about when and what gets scanned:

scan_user_messages:

runs at the moment the user message enters ADK
implemented in on_user_message_callback() in dlp_plugin.py (line 122)
scans just the incoming user_message
this is the earliest protection point
scan_llm_requests:

runs right before an agent sends a request to the model
implemented in before_model_callback() in dlp_plugin.py (line 144)
scans llm_request.contents
this can include more than the original user prompt:
conversation history
system/instruction text
agent-generated intermediate context
tool outputs that are about to be sent to the model
delegated/sub-agent context
So they are related, but not the same.

A simple way to think about it:

scan_user_messages = protect data at ingress
scan_llm_requests = protect everything before it leaves for the model
Example:
If the user sends My SSN is 123-45-6789, then:

scan_user_messages=True masks it as soon as it arrives
later, scan_llm_requests=True scans the full model payload again before the LLM call
Why both can matter:

if user-message scanning misses something, LLM-request scanning gets another chance
if sensitive data is introduced later by tools/memory/agent reasoning, scan_user_messages will never see it, but scan_llm_requests can
So yes, there is overlap, but scan_llm_requests is broader and later in the pipeline.


hmm.. got it.. i cannot create filter on a use-case level isn't it.. it will be difficult to manage


Not with the current design, yes. Right now the filtering is mostly:

by scan stage: user message, LLM request/response, tool call/result
by agent name: allowlist/blocklist
by info type: email, DOB, SSN, etc.
There is no real “use-case level” filter like:

only for offer-related queries
only for support flows
only for onboarding journey
only when tool user_lookup is called from agent orchestrator
So if your use cases cut across the same agents, it can get hard to manage cleanly.

What you have today is coarse-grained control, not business-flow control.

Typical ways to support use-case-level control would be one of these:

Add a context tag or use_case into the invocation/session metadata, then let the plugin decide whether to scan based on that.
Add per-tool rules, like scan_tool_calls_for=["user_lookup", "crm_search"].
Add per-route or per-endpoint profiles, so one API path uses one DLP config and another path uses a different one.
Support policy objects, for example:
offers_policy
support_policy
kyc_policy
Right now your plugin does not appear to have that abstraction. It is centered on agent/stage filtering, not use-case filtering.

So short answer: yes, with the current implementation, use-case-level filtering is not really supported and may become difficult to maintain as flows grow.

If you want, I can sketch a clean minimal design to add use-case-based DLP policies without making the plugin too complex.