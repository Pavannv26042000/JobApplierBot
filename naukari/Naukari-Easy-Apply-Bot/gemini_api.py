"""
Install the Google AI Python SDK

$ pip install google-generativeai

See the getting started guide for more information:
https://ai.google.dev/gemini-api/docs/get-started/python
"""

import os
import google.generativeai as genai

# Replace with your actual API key
genai.configure(api_key="AIzaSyCHD3BOd8-aNp_KCEs_JE0S7uc7Zfy3NOE")

# Create the model
generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 1000,
    "response_mime_type": "text/plain",
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=generation_config,
    system_instruction=(
        "Remember the provided resume data when answering questions. "
        "Be concise: min 1 word, average 3 words, max 5 words. "
        "For multiple-choice questions, return only the index number."
    ),
)

# Fixed and valid resume JSON
resume_data = """
{
  "name": "Pavan NV",
  "contact": {
    "phone": "+91 7899569686",
    "email": "pavankowshik200@gmail.com",
    "linkedin": "https://www.linkedin.com/in/pavan-n-v-359551197"
  },
  "education": [
    {
      "degree": "B.E. in Information Science and Engineering",
      "institution": "Sri Venkateshwara College of Engineering",
      "startDate": "2018",
      "endDate": "2022",
      "cgpa": "7.7"
    }
  ],
  "skills": {
    "languages": ["Java", "Go", "SQL"],
    "frameworks": ["Spring Boot", "JavaFX", "AWT"],
    "tools": ["Visual Studio Code", "IntelliJ", "Eclipse", "Git", "Confluence", "Enterprise Architect"],
    "scripting": ["Bash"],
    "os": ["Linux"],
    "softSkills": ["Communication", "Collaboration", "Adaptability", "Time Management"]
  },
  "experience": [
    {
      "title": "Software Engineer",
      "company": "Alten Global Technology Pvt Ltd",
      "location": "Bengaluru, India",
      "startDate": "Nov 2022",
      "endDate": "Present",
      "responsibilities": [
        "Developed charts and processed cartographic data for sonar systems using Java and Spring Boot.",
        "Performed mosaic calculations for active, passive, and ray data, improving analysis efficiency by 15%.",
        "Integrated calculations into real-time apps for seamless system performance."
      ]
    },
    {
      "title": "Software Engineer",
      "company": "Sixdee Technologies Pvt Ltd",
      "location": "Bengaluru, India",
      "startDate": "Apr 2022",
      "endDate": "Nov 2022",
      "responsibilities": [
        "Built a Voice Mail Service (VMS) with Java and Spring Boot, used by 10,000+ users.",
        "Integrated VMS with systems to reduce response time by 15%.",
        "Collaborated to deliver on milestones and meet client expectations."
      ]
    }
  ],
  "projects": [
    {
      "name": "Sonar Application for Ultra CSS",
      "year": "2023",
      "description": "Designed a JavaFX-Spring Boot sonar app for real-time visualization aligned to client requirements."
    },
    {
      "name": "Test Harness Tool",
      "description": "Built tool to test sonar plugins on laptops, replacing need for lab environment."
    },
    {
      "name": "Employee Engagement Tool",
      "description": "Created tool to help new joiners onboard and learn project-related content efficiently."
    }
  ],
  "activities": [
    "Led a team to win two hackathons, demonstrating technical and leadership skills."
  ]
}
"""

chat_session = model.start_chat(
    history=[
        {
            "role": "user",
            "parts": [resume_data],
        },
        {
            "role": "model",
            "parts": [
                "Resume data received. I'll use this information to answer questions concisely."
            ],
        },
        {
            "role": "user",
            "parts": [
                "Remember this resume data. Answer questions using it. "
                "Responses: min 1 word, average 3 words, max 5 words."
            ],
        },
        {
            "role": "model",
            "parts": [
                "Understood. I'll answer using resume data: min 1 word, average 3 words, max 5 words."
            ],
        },
    ]
)


def bard_flash_response(question) -> str:
    try:
        response = chat_session.send_message(question)
        return response.text
    except Exception as e:
        print(f"Gemini API error: {e}")
        return "0"  # Always return string for consistency