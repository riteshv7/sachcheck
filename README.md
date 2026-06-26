<div align="center">
  <img src="https://img.icons8.com/color/94/shield.png" width="80" height="80" />
  <h1>SachCheck Fact-Checking</h1>
  <p><i>A full-stack truth-verification platform and browser extension</i></p>

  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" />
  <img src="https://img.shields.io/badge/Chrome_Extension-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white" />
</div>

<br />

## 📖 Overview

**SachCheck** is an automated fact-checking utility engineered to combat misinformation across the web. It features a robust backend API that analyzes claims and a convenient browser extension that allows users to instantly verify news articles and social media posts while they browse.

The project is structured into three main components:
1. **Backend**: A high-performance Python API that processes text and cross-references claims against verified databases.
2. **Extension**: A Chrome browser extension that highlights dubious claims and provides truth-verification scores.
3. **Analysis Engine**: A suite of Natural Language Processing (NLP) scripts that power the truth-scoring algorithm.

## ⚙️ Tech Stack

- **Backend**: Python, FastAPI
- **Frontend / Extension**: JavaScript, HTML/CSS
- **Data Analysis**: Pandas, Scikit-learn, NLP methodologies
- **Deployment**: Vercel

## 🚀 Setup & Installation

### Backend Setup
1. Navigate to the `backend` directory.
2. Install dependencies: `pip install -r ../requirements.txt`.
3. Start the server (e.g., via `uvicorn`).

### Extension Installation
1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** in the top right.
3. Click **Load unpacked** and select the `extension/` directory from this repository.
4. The SachCheck icon will appear in your browser toolbar!

## 🤝 Contributing
Contributions, issues, and feature requests are welcome! Check out the [issues page](https://github.com/riteshv7/sachcheck/issues).
