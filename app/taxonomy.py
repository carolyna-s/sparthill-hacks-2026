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

# Suggestions for the industry field (an autocomplete, like LinkedIn's). Anything the user
# types that isn't here is kept as typed.
INDUSTRIES = [
    "Accounting", "Advertising Services", "Aerospace and Defense", "Agriculture", "Airlines and Aviation",
    "Animation and Gaming", "Architecture and Planning", "Armed Forces", "Artificial Intelligence",
    "Automotive", "Banking", "Biotechnology Research", "Book and Periodical Publishing",
    "Broadcast Media", "Business Consulting and Services", "Chemical Manufacturing",
    "Civic and Social Organizations", "Civil Engineering", "Computer and Network Security",
    "Computer Games", "Computer Hardware Manufacturing", "Construction", "Consumer Electronics",
    "Consumer Goods", "Cosmetics", "Data Infrastructure and Analytics", "Dairy Product Manufacturing",
    "Defense and Space Manufacturing", "Design Services", "E-Learning Providers", "Education Administration",
    "Electric Power Generation", "Entertainment Providers", "Environmental Services", "Events Services",
    "Executive Offices", "Facilities Services", "Farming", "Fashion and Apparel", "Financial Services",
    "Fine Art", "Food and Beverage Services", "Food and Beverage Manufacturing", "Fundraising",
    "Furniture", "Government Administration", "Government Relations Services", "Graphic Design",
    "Higher Education", "Hospitality", "Hospitals and Health Care", "Human Resources Services",
    "Industrial Machinery Manufacturing", "Information Services", "Insurance", "International Affairs",
    "International Trade and Development", "Investment Banking", "Investment Management",
    "IT Services and IT Consulting", "Law Enforcement", "Law Practice", "Legal Services",
    "Libraries", "Logistics and Supply Chain", "Luxury Goods and Jewelry", "Manufacturing",
    "Maritime Transportation", "Market Research", "Marketing Services", "Mechanical Engineering",
    "Media Production", "Medical Devices", "Medical Practices", "Mental Health Care", "Mining",
    "Motion Pictures and Film", "Museums, Historical Sites, and Zoos", "Musicians",
    "Nanotechnology Research", "Newspaper Publishing", "Non-profit Organizations", "Oil and Gas",
    "Online Audio and Video Media", "Outsourcing and Offshoring Consulting", "Packaging and Containers",
    "Performing Arts", "Pharmaceutical Manufacturing", "Philanthropic Fundraising Services",
    "Photography", "Political Organizations", "Primary and Secondary Education", "Printing Services",
    "Professional Training and Coaching", "Public Health", "Public Policy Offices",
    "Public Relations and Communications Services", "Public Safety", "Real Estate",
    "Recreational Facilities", "Religious Institutions", "Renewable Energy", "Research Services",
    "Restaurants", "Retail", "Robotics Engineering", "Semiconductor Manufacturing", "Social Work",
    "Software Development", "Spectator Sports", "Sporting Goods", "Staffing and Recruiting",
    "Technology, Information and Internet", "Telecommunications", "Textile Manufacturing",
    "Think Tanks", "Translation and Localization", "Transportation", "Travel Arrangements",
    "Truck Transportation", "Utilities", "Venture Capital and Private Equity", "Veterinary Services",
    "Warehousing and Storage", "Wellness and Fitness Services", "Wholesale", "Wine and Spirits",
    "Wireless Services", "Writing and Editing",
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

EDUCATION_PATHS = [
    "4-year university", "community college transfer", "graduate degree", "bootcamp / self-taught",
    "first-generation college student", "international student", "returning / adult learner",
]

# Multi-select (tag picker) fields on the profile form.
TAXONOMY = {
    "availability": AVAILABILITY,
    "languages": LANGUAGES,
    "development_areas": DEVELOPMENT_AREAS,
    "goals": GOALS,
    "education_paths": EDUCATION_PATHS,
}
