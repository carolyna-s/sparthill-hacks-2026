"""Fixed vocabularies shared by profiles, applications, and the matching engine.

Keeping these as tags (not free text) is what makes score-based matching possible.
Edit freely; existing profiles keep whatever tags they already have.
"""

# --- hard filters: a pair must overlap on these to be matched at all ----------

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
PERIODS = ["morning", "afternoon", "evening", "night"]
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

# Sectors for partial industry credit in matching: a mentor in the same sector but a different
# industry scores matching.GROUP_CREDIT. An industry can sit in more than one sector when it
# genuinely straddles them. Typed industries outside the list get no sector (embedding only).
INDUSTRY_GROUPS = {
    "Finance": ["Accounting", "Banking", "Financial Services", "Insurance", "Investment Banking",
                "Investment Management", "Venture Capital and Private Equity"],
    "Software and IT": ["Artificial Intelligence", "Computer and Network Security", "Computer Games",
                        "Data Infrastructure and Analytics", "E-Learning Providers", "Information Services",
                        "IT Services and IT Consulting", "Software Development",
                        "Technology, Information and Internet", "Telecommunications", "Wireless Services"],
    "Hardware and electronics": ["Computer Hardware Manufacturing", "Consumer Electronics", "Medical Devices",
                                 "Nanotechnology Research", "Robotics Engineering", "Semiconductor Manufacturing"],
    "Engineering and manufacturing": ["Aerospace and Defense", "Automotive", "Chemical Manufacturing",
                                      "Civil Engineering", "Defense and Space Manufacturing",
                                      "Industrial Machinery Manufacturing", "Manufacturing", "Mechanical Engineering",
                                      "Packaging and Containers", "Robotics Engineering", "Textile Manufacturing"],
    "Construction and real estate": ["Architecture and Planning", "Civil Engineering", "Construction",
                                     "Facilities Services", "Real Estate"],
    "Energy and environment": ["Electric Power Generation", "Environmental Services", "Mining", "Oil and Gas",
                               "Renewable Energy", "Utilities"],
    "Life sciences": ["Biotechnology Research", "Medical Devices", "Nanotechnology Research",
                      "Pharmaceutical Manufacturing", "Research Services"],
    "Health care": ["Hospitals and Health Care", "Medical Devices", "Medical Practices", "Mental Health Care",
                    "Pharmaceutical Manufacturing", "Public Health", "Veterinary Services",
                    "Wellness and Fitness Services"],
    "Education": ["E-Learning Providers", "Education Administration", "Higher Education", "Libraries",
                  "Primary and Secondary Education", "Professional Training and Coaching"],
    "Media and entertainment": ["Animation and Gaming", "Book and Periodical Publishing", "Broadcast Media",
                                "Computer Games", "Entertainment Providers", "Media Production",
                                "Motion Pictures and Film", "Newspaper Publishing", "Online Audio and Video Media",
                                "Printing Services", "Spectator Sports", "Writing and Editing"],
    "Arts and design": ["Animation and Gaming", "Design Services", "Fine Art", "Graphic Design",
                        "Museums, Historical Sites, and Zoos", "Musicians", "Performing Arts", "Photography"],
    "Marketing and communications": ["Advertising Services", "Market Research", "Marketing Services",
                                     "Public Relations and Communications Services", "Translation and Localization",
                                     "Writing and Editing"],
    "Business services": ["Business Consulting and Services", "Events Services", "Executive Offices",
                          "Human Resources Services", "Outsourcing and Offshoring Consulting",
                          "Professional Training and Coaching", "Staffing and Recruiting"],
    "Law": ["Law Practice", "Legal Services"],
    "Government and public service": ["Armed Forces", "Government Administration", "Government Relations Services",
                                      "International Affairs", "International Trade and Development",
                                      "Law Enforcement", "Political Organizations", "Public Health",
                                      "Public Policy Offices", "Public Safety", "Think Tanks"],
    "Nonprofit and social impact": ["Civic and Social Organizations", "Fundraising", "Non-profit Organizations",
                                    "Philanthropic Fundraising Services", "Religious Institutions", "Social Work"],
    "Consumer goods and retail": ["Consumer Goods", "Cosmetics", "Fashion and Apparel", "Furniture",
                                  "Luxury Goods and Jewelry", "Retail", "Sporting Goods", "Wholesale"],
    "Food and agriculture": ["Agriculture", "Dairy Product Manufacturing", "Farming",
                             "Food and Beverage Manufacturing", "Wine and Spirits"],
    "Hospitality and travel": ["Events Services", "Food and Beverage Services", "Hospitality",
                               "Recreational Facilities", "Restaurants", "Travel Arrangements"],
    "Transportation and logistics": ["Airlines and Aviation", "Logistics and Supply Chain", "Maritime Transportation",
                                     "Transportation", "Truck Transportation", "Warehousing and Storage", "Wholesale"],
}

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
