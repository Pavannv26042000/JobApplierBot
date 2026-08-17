FROM python:3.11-slim

# Install Chrome + ChromeDriver
RUN apt-get update && apt-get install -y \
    wget \
    gnupg2 \
    unzip \
    xvfb \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm || true

# Copy project
COPY . .

# Create necessary directories
RUN mkdir -p logs reports custom_resumes tailored_resumes bible n8n_workflows

# Set display for headless Chrome
ENV DISPLAY=:99

# Default command
CMD ["python", "orchestrator.py", "--platform", "both", "--mode", "full"]
