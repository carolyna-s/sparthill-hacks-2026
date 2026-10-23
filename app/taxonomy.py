"""Fixed vocabularies shared by profiles, applications, and the matching engine.

Keeping these as tags (not free text) is what makes score-based matching possible.
Edit freely; existing profiles keep whatever tags they already have.
"""

CAREER_INTERESTS = [
    "software engineering", "data science", "product management", "design",
    "finance", "consulting", "healthcare", "education", "entrepreneurship",
    "nonprofit", "marketing", "law", "research", "public policy",
]

GOALS = [
    "land first job", "switch careers", "get promoted", "start a business",
    "apply to grad school", "build a network", "find a niche", "lead a team",
]

DEVELOPMENT_AREAS = [
    "resume and interviewing", "public speaking", "technical skills", "leadership",
    "networking", "negotiation", "time management", "confidence", "writing",
    "work-life balance",
]

TAXONOMY = {
    "career_interests": CAREER_INTERESTS,
    "goals": GOALS,
    "development_areas": DEVELOPMENT_AREAS,
}
