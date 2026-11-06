"""Conservative, local conversation routing before retrieval or ticket creation.

Match clear social/off-topic turns only. Unknown wording continues through the
existing safety and support flow; a missing support keyword is not a rejection.
"""

import re
from dataclasses import dataclass

from support_agent.schemas import Message, Role


@dataclass(frozen=True)
class ConversationReply:
    category: str
    message: str


_REDIRECT = (
    "I'm here to help with store support. I can help with orders, returns, "
    "shipping, billing, accounts, and products. What issue are you having?"
)
_INSULT_ONLY = re.compile(
    r"(?:(?:fuck|screw) (?:you|u)|(?:you(?:re| are)? )?(?:an? )?"
    r"(?:idiot|moron|asshole|stupid|useless)|shut (?:the fuck )?up|fuck off)"
    r"(?: (?:bro|man|dude|lol))*"
)
_FOLLOWUPS = {
    "why",
    "really",
    "really why",
    "why is that",
    "what do you mean",
    "really do you think this will happen",
    "do you think this will happen",
    "will someone actually reply",
    "will anyone reply",
    "will this happen",
    "are you sure",
    "what happens next",
    "when will they reply",
}
_OFF_TOPIC = re.compile(
    r"^(?:please )?(?:tell me (?:a joke|a story)|write (?:me )?(?:a poem|a song)|"
    r"(?:what(?:s| is)|how is) the weather|who won (?:the )?|"
    r"what is the capital of|write (?:me )?(?:a |some )?(?:python|javascript|code|script))\b"
)


def route_conversation(text: str, history: list[Message]) -> ConversationReply | None:
    normalized = " ".join(re.sub(r"[^a-z0-9\s]", "", text.lower()).split())
    if normalized in _FOLLOWUPS:
        # Only the most recent assistant reply is authoritative for this follow-up.
        previous = next((m.content for m in reversed(history) if m.role == Role.ASSISTANT), "")
        if (
            "saved your request for support review" in previous
            or "saved for staff review" in previous
        ):
            ticket = re.search(r"\btkt_[a-f0-9]{12}\b", previous)
            reference = f" Your existing reference is {ticket.group()}." if ticket else ""
            return ConversationReply(
                "existing_handoff",
                "Your request is saved for staff review. A reply depends on staff reviewing "
                "the inbox; I can't guarantee a response time. You can check this chat for "
                "a reply." + reference,
            )
        return ConversationReply("clarification", "Which part would you like me to explain?")
    if _INSULT_ONLY.fullmatch(normalized):
        return ConversationReply("insult_only", _REDIRECT)
    # Don't reject a mixed turn with a genuine store issue just because it also
    # mentions an off-topic subject. Let safety and support processing handle it.
    support = re.search(
        r"\b(?:orders?|returns?|refunds?|shipping|delivery|billing|account|"
        r"products?|warranty|chairs?|desks?|lamps?|payment|charged|package)\b",
        normalized,
    )
    if not support and _OFF_TOPIC.search(normalized):
        return ConversationReply("out_of_scope", _REDIRECT)
    return None
