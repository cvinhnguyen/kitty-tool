#!/usr/bin/env python3
"""Kitty-Tools Answer Viewer - Streamlit web app.

Read-only Kahoot quiz answer lookup by Quiz ID (UUID) or challenge PIN,
using Kahoot's own public REST API. No live-game / bot functionality.
"""
import json
import re
import time
import ssl
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

import streamlit as st

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def extract_uuid(value):
    value = (value or "").strip()
    match = UUID_PATTERN.search(value)
    return match.group(0) if match else value


class KahootAPI:
    BASE_API_URL = "https://play.kahoot.it/rest/kahoots/"
    CHALLENGE_API_URL = "https://kahoot.it/rest/challenges/pin/"
    REQUEST_TIMEOUT = 15

    def __init__(self):
        self.ssl_context = ssl.create_default_context()

    def _get_headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }

    def _make_request(self, url, max_retries=2):
        for attempt in range(max_retries):
            try:
                request = Request(url, headers=self._get_headers())
                with urlopen(request, timeout=self.REQUEST_TIMEOUT, context=self.ssl_context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as e:
                if e.code == 404:
                    return {"error": "Quiz not found. The ID may be incorrect."}
                if e.code == 400:
                    return {"error": "Bad request. Kahoot rejected the ID or PIN format."}
                if e.code == 429 and attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                if e.code == 403:
                    return {"error": "Access forbidden (rate limited or private quiz)."}
                return {"error": f"HTTP Error: {e.code} - {e.reason}"}
            except URLError as e:
                return {"error": f"Connection error: {e.reason}"}
            except json.JSONDecodeError:
                return {"error": "Failed to parse the response from Kahoot servers."}
            except Exception as e:
                return {"error": f"Unexpected error: {e}"}
        return {"error": "All retry attempts failed"}

    @staticmethod
    def get_quiz_by_id(quiz_id):
        quiz_id = extract_uuid(quiz_id)
        if not UUID_PATTERN.fullmatch(quiz_id):
            return {"error": "Invalid Quiz ID format. Use the UUID from a Kahoot share/details URL."}
        api = KahootAPI()
        return api._make_request(f"{api.BASE_API_URL}{quiz_id}")

    @staticmethod
    def get_quiz_id_from_pin(pin):
        if not pin.isdigit():
            return {"error": "PIN must contain only digits"}
        api = KahootAPI()
        result = api._make_request(f"{api.CHALLENGE_API_URL}{pin}")
        if "error" not in result and "id" in result:
            return {"quiz_id": result["id"]}
        if "error" not in result:
            return {"error": "No quiz ID found in response"}
        return {"error": f"{result['error']} (only works for challenge/assignment PINs, not live game PINs)"}


def clean_text(text):
    if not text:
        return ""
    text = str(text)
    for old, new in [
        ("<p>", ""), ("</p>", ""), ("<strong>", ""), ("</strong>", ""),
        ("<b>", ""), ("</b>", ""), ("<br/>", "\n"), ("<br>", "\n"),
        ("<span>", ""), ("</span>", ""),
    ]:
        text = text.replace(old, new)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace('\\"', '"').strip()


def get_question_details(quiz_data, index):
    question = quiz_data["questions"][index]
    qtype = question.get("type", "unknown")
    details = {"type": qtype}
    if qtype == "content":
        details["title"] = clean_text(question.get("title", ""))
        details["description"] = clean_text(question.get("description", ""))
        return details
    details["question"] = clean_text(question.get("question", ""))
    details["choices"] = [
        {"answer": clean_text(c.get("answer", "")), "correct": c.get("correct", False)}
        for c in question.get("choices", [])
    ]
    return details


def get_answers(details):
    if details["type"] == "content":
        return None
    if details["type"] == "jumble":
        return [c["answer"] for c in details["choices"]]
    return [c["answer"] for c in details["choices"] if c["correct"]] or None


st.set_page_config(page_title="Kitty-Tools Answer Viewer", page_icon="🐱")
st.title("🐱 Kitty-Tools - Kahoot Answer Viewer")
st.caption("Read-only lookup against Kahoot's public quiz API. Paste a Quiz ID (UUID), a share/details URL, or a challenge PIN.")

user_input = st.text_input("Quiz ID / share URL / challenge PIN")

if st.button("Fetch answers", type="primary") and user_input.strip():
    raw = user_input.strip()
    with st.spinner("Fetching..."):
        if raw.isdigit():
            pin_result = KahootAPI.get_quiz_id_from_pin(raw)
            if "error" in pin_result:
                st.error(pin_result["error"])
                st.stop()
            quiz_id = pin_result["quiz_id"]
        else:
            quiz_id = extract_uuid(raw)

        quiz_data = KahootAPI.get_quiz_by_id(quiz_id)

    if "error" in quiz_data:
        st.error(quiz_data["error"])
        st.stop()

    st.subheader(quiz_data.get("title", "Untitled Quiz"))
    st.write(f"**Creator:** {quiz_data.get('creator_username', 'Unknown')}")
    questions = quiz_data.get("questions", [])
    st.write(f"**Questions:** {len(questions)}")
    st.divider()

    export_lines = [f"Title: {quiz_data.get('title', 'Untitled Quiz')}", ""]

    for i in range(len(questions)):
        details = get_question_details(quiz_data, i)
        if details["type"] == "content":
            st.markdown(f"**Slide {i + 1}:** {details['title']}")
            if details["description"]:
                st.caption(details["description"])
            export_lines.append(f"SLIDE {i + 1}: {details['title']}")
        else:
            answers = get_answers(details)
            st.markdown(f"**Q{i + 1}:** {details['question']}")
            st.write("Answer(s): " + (", ".join(answers) if answers else "None found"))
            export_lines.append(f"QUESTION {i + 1}: {details['question']}")
            export_lines.append(f"Answer(s): {', '.join(answers) if answers else 'None found'}")
        export_lines.append("")

    st.download_button(
        "Download answers as .txt",
        data="\n".join(export_lines),
        file_name="kahoot_answers.txt",
    )
