"""Fixed vocabularies shared by profiles, applications, and the matching engine.

Keeping these as tags (not free text) is what makes score-based matching possible.
Edit freely; existing profiles keep whatever tags they already have.
"""

# --- hard filters: a pair must overlap on these to be matched at all ----------

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
PERIODS = ["morning", "afternoon"]
AVAILABILITY = [f"{day} - {period}" for day in DAYS for period in PERIODS]

LANGUAGES = [
    "English", "Spanish", "Mandarin", "Cantonese", "Vietnamese", "Tagalog", "Korean", "Hindi",
    "Punjabi", "Arabic", "French", "Portuguese", "Japanese", "Russian", "ASL",
]

# --- soft filters: weighted into the match score -------------------------------

# Industry / fields of interest
CAREER_INTERESTS = [
    "software engineering", "data science", "product management", "design",
    "finance", "consulting", "healthcare", "education", "entrepreneurship",
    "nonprofit", "marketing", "law", "research", "public policy",
]

GOALS = [
    "land first job", "switch careers", "get promoted", "start a business",
    "apply to grad school", "build a network", "find a niche", "lead a team",
]

# Skills to learn (mentee) / skills they can teach (mentor)
DEVELOPMENT_AREAS = [
    "resume and interviewing", "public speaking", "technical skills", "leadership",
    "networking", "negotiation", "time management", "confidence", "writing",
    "work-life balance",
]

# Where the mentee wants to be in 3-5 years / tracks the mentor can speak to
CAREER_OUTLOOK = [
    "individual contributor / specialist", "people manager", "executive leadership",
    "founder / entrepreneur", "academia / research", "public service", "still exploring",
]

SENIORITY = [
    "early career (0-3 years)", "mid-level (3-7 years)", "senior (7-15 years)", "executive (15+ years)",
]

MENTORING_STYLE = [
    "hands-on guidance", "coaching through questions", "accountability and goal tracking",
    "sounding board", "networking and introductions",
]

COMPANY_TYPES = [
    "startup", "mid-size company", "large corporation", "nonprofit", "government / public sector",
    "academia", "consulting / agency", "self-employed",
]

EDUCATION_PATHS = [
    "4-year university", "community college transfer", "graduate degree", "bootcamp / self-taught",
    "first-generation college student", "international student", "returning / adult learner",
]

TAXONOMY = {
    "availability": AVAILABILITY,
    "languages": LANGUAGES,
    "career_interests": CAREER_INTERESTS,
    "goals": GOALS,
    "development_areas": DEVELOPMENT_AREAS,
    "career_outlook": CAREER_OUTLOOK,
    "seniority": SENIORITY,
    "mentoring_style": MENTORING_STYLE,
    "company_types": COMPANY_TYPES,
    "education_paths": EDUCATION_PATHS,
}
