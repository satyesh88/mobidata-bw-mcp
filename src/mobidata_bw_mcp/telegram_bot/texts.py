ATTRIBUTION = "Daten: MobiData BW® / NVBW und Datengeber"

EXAMPLES = (
    "🅿️ Parking near Stuttgart Hbf right now",
    "🛴 E-scooters near Heilbronn Hbf",
    "⚡ Fast chargers at Weinsberger Kreuz",
    "🚧 Roadworks around Heilbronn this week",
)

START_TEXT = (
    "<b>MobiData BW Assistant</b> answers mobility questions for Baden-Württemberg.\n\n"
    "📍 Share your location and ask “What’s near me?”\n\n"
    "<i>Your messages are processed by an AI service (Anthropic) to answer them. "
    "Nothing is stored after 30 minutes. Shared locations are used only for your "
    "current question.</i>"
)

HELP_TEXT = (
    "Ask about parking, charging, sharing, transit, roadworks, traffic signs, or "
    "MobiData BW datasets. Share a location for nearby results. Use /reset to clear context."
)

ABOUT_TEXT = (
    "<b>MobiData BW Assistant (Demo)</b>\n"
    "Built by Satyesh Shivam on the open-source MobiData BW MCP server. "
    "Public mobility data remains subject "
    "to each source’s licence and freshness.\n"
    '<a href="https://github.com/satyes88/mobidata-bw-mcp">GitHub</a>'
)

RESET_TEXT = "Conversation and shared location cleared."
LOCATION_TEXT = "📍 Location saved for 30 minutes. Now ask what’s near you."
RATE_LIMIT_TEXT = "You’ve reached the demo limit. Please try again in an hour."
BUDGET_TEXT = "The demo budget for today is used up. Please try again tomorrow."
TIMEOUT_TEXT = (
    "That took too long. I’ll answer in parts: ask about parking first, then the station."
)
ERROR_TEXT = "Sorry, I couldn’t answer that just now. Please try again."
PRIVATE_TEXT = "This demo only answers in a private chat."
NOT_ALLOWED_TEXT = "This private demo is not available for this account."
