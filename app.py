import json

import httpx
import streamlit as st
from openai import OpenAI
from pypdf import PdfReader
from supabase import create_client


QUIZ_SYSTEM_PROMPT = """당신은 학습 퀴즈를 만드는 도우미입니다.
주어진 요약을 바탕으로 4지선다 퀴즈 3문항을 만드세요.
각 문항은 question, options(4개), answer(정답 인덱스, 0부터 시작), explanation을 포함해야 합니다.
결과는 {"questions": [...]} 형태의 JSON으로 반환하세요.
"""


st.set_page_config(
    page_title="AI 학습 정리 노트",
    page_icon="📚",
    layout="wide",
)


@st.cache_resource
def get_supabase_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def render_saved_summaries():
    st.subheader("저장 기록")
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("Summaries")
            .select("id, filename, summary, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        records = response.data or []
    except Exception as error:
        st.error(f"저장 기록을 불러오는 중 오류가 발생했습니다: {error}")
        return

    if not records:
        st.info("아직 저장된 요약이 없습니다.")
        return

    for record in records:
        summary = record.get("summary") or {}
        summary_preview = str(summary.get("핵심 요약", "내용 없음"))
        if len(summary_preview) > 100:
            summary_preview = f"{summary_preview[:100]}..."

        filename_column, date_column, preview_column, delete_column = st.columns(
            [2, 2, 5, 1]
        )
        filename_column.write(record.get("filename", "이름 없음"))
        date_column.write(record.get("created_at", ""))
        preview_column.write(summary_preview)
        if delete_column.button("삭제", key=f"delete_summary_{record['id']}"):
            try:
                supabase.table("Summaries").delete().eq("id", record["id"]).execute()
                st.rerun()
            except Exception as error:
                st.error(f"저장 기록을 삭제하는 중 오류가 발생했습니다: {error}")


def render_quiz(summary_result, summary_record_id, document_key):
    st.subheader("학습 퀴즈")

    if not summary_result:
        st.info("먼저 요약 탭에서 요약을 생성해주세요.")
        return
    if not summary_record_id:
        st.info("퀴즈를 저장하려면 먼저 요약을 저장해주세요.")
        return

    if st.button("퀴즈 생성", type="primary"):
        try:
            api_key = st.secrets["OPENAI_API_KEY"]
            if not api_key:
                raise KeyError("OPENAI_API_KEY")

            client = OpenAI(
                api_key=api_key,
                http_client=httpx.Client(trust_env=False, timeout=60.0),
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(summary_result, ensure_ascii=False),
                    },
                ],
                response_format={"type": "json_object"},
            )
            quiz_result = json.loads(response.choices[0].message.content)
            questions = quiz_result.get("questions", [])
            if len(questions) != 3:
                raise ValueError("퀴즈 응답에 3개 문항이 필요합니다.")

            supabase = get_supabase_client()
            supabase.table("Summaries").update({"quiz": quiz_result}).eq(
                "id", summary_record_id
            ).execute()
            st.session_state.quiz_result = quiz_result
            st.success("퀴즈를 생성하고 저장했습니다.")
        except (FileNotFoundError, KeyError):
            st.error(
                "OpenAI API 키가 설정되지 않았습니다. "
                ".streamlit/secrets.toml 파일에 OPENAI_API_KEY를 추가하세요."
            )
        except Exception as error:
            st.error(f"퀴즈를 생성하는 중 오류가 발생했습니다: {error}")

    quiz_result = st.session_state.get("quiz_result")
    if not quiz_result:
        return

    for question_number, question in enumerate(quiz_result.get("questions", []), start=1):
        st.markdown(f"#### {question_number}. {question.get('question', '문제 없음')}")
        options = question.get("options", [])
        selected_option = st.radio(
            "보기",
            options,
            index=None,
            key=f"quiz_option_{document_key}_{question_number}",
            label_visibility="collapsed",
        )
        if selected_option is not None:
            selected_index = options.index(selected_option)
            answer_index = question.get("answer")
            if selected_index == answer_index:
                st.success("정답입니다.")
            else:
                st.error("오답입니다.")
            st.info(f"해설: {question.get('explanation', '해설 없음')}")


st.sidebar.title("문서 업로드")
uploaded_file = st.sidebar.file_uploader(
    "PDF 파일을 업로드하세요",
    type=["pdf"],
    accept_multiple_files=False,
)

st.title("AI 학습 정리 노트")
st.write("PDF를 업로드하면 문서의 텍스트를 페이지별로 확인할 수 있습니다.")

if "summary_result" not in st.session_state:
    st.session_state.summary_result = None
if "summary_document_key" not in st.session_state:
    st.session_state.summary_document_key = None
if "summary_record_id" not in st.session_state:
    st.session_state.summary_record_id = None
if "quiz_result" not in st.session_state:
    st.session_state.quiz_result = None

if uploaded_file is not None:
    try:
        reader = PdfReader(uploaded_file)
        page_count = len(reader.pages)
        page_texts = [
            page.extract_text() or "(이 페이지에서 추출된 텍스트가 없습니다.)"
            for page in reader.pages
        ]
        document_key = f"{uploaded_file.name}:{uploaded_file.size}"

        if st.session_state.summary_document_key != document_key:
            st.session_state.summary_document_key = document_key
            st.session_state.summary_result = None
            st.session_state.summary_record_id = None
            st.session_state.quiz_result = None

        st.sidebar.subheader("문서 정보")
        st.sidebar.write(f"**파일명**  \n{uploaded_file.name}")
        st.sidebar.metric("총 페이지 수", f"{page_count}페이지")

        original_tab, summary_tab, quiz_tab, history_tab = st.tabs(
            ["원문", "요약", "퀴즈", "저장 기록"]
        )
        with original_tab:
            st.subheader("페이지별 원문")
            for page_number, page_text in enumerate(page_texts, start=1):
                with st.expander(f"{page_number}페이지", expanded=True):
                    st.text_area(
                        f"{page_number}페이지 텍스트",
                        value=page_text,
                        height=240,
                        label_visibility="collapsed",
                    )

        with summary_tab:
            st.subheader("AI 요약")
            if st.button("요약하기", type="primary"):
                try:
                    api_key = st.secrets["OPENAI_API_KEY"]
                    if not api_key:
                        raise KeyError("OPENAI_API_KEY")

                    client = OpenAI(api_key=api_key)
                    full_text = "\n\n".join(page_texts)
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "핵심 요약(3문장), 주요 키워드(5개), 난이도(상/중/하)를 "
                                    "JSON으로 반환하세요. 다음 JSON 형식을 지키세요: "
                                    '{"핵심 요약": "3문장", "주요 키워드": ["키워드 1", "키워드 2", '
                                    '"키워드 3", "키워드 4", "키워드 5"], "난이도": "상/중/하"}'
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"다음 PDF 텍스트를 분석하세요:\n\n{full_text}",
                            },
                        ],
                        response_format={"type": "json_object"},
                    )
                    summary_result = json.loads(response.choices[0].message.content)
                    st.session_state.summary_result = summary_result
                    st.session_state.summary_record_id = None
                    st.session_state.quiz_result = None
                except (FileNotFoundError, KeyError):
                    st.error(
                        "OpenAI API 키가 설정되지 않았습니다. "
                        ".streamlit/secrets.toml 파일에 OPENAI_API_KEY를 추가하세요."
                    )
                except Exception as error:
                    st.error(f"요약을 생성하는 중 오류가 발생했습니다: {error}")

            if st.session_state.summary_result:
                summary_result = st.session_state.summary_result
                st.markdown("#### 핵심 요약")
                st.write(summary_result.get("핵심 요약", "내용 없음"))
                st.markdown("#### 주요 키워드")
                keywords = summary_result.get("주요 키워드", [])
                st.write(" · ".join(keywords) if isinstance(keywords, list) else keywords)
                st.markdown("#### 난이도")
                st.write(summary_result.get("난이도", "내용 없음"))
                if st.button("저장", type="secondary"):
                    try:
                        supabase = get_supabase_client()
                        insert_response = supabase.table("Summaries").insert(
                            {
                                "filename": uploaded_file.name,
                                "summary": summary_result,
                                "quiz": None,
                            }
                        ).execute()
                        inserted_rows = insert_response.data or []
                        if not inserted_rows:
                            raise ValueError("저장된 요약의 id를 확인할 수 없습니다.")
                        st.session_state.summary_record_id = inserted_rows[0]["id"]
                        st.success("요약 결과를 저장했습니다.")
                    except Exception as error:
                        st.error(f"요약 결과를 저장하는 중 오류가 발생했습니다: {error}")

        with quiz_tab:
            render_quiz(
                st.session_state.summary_result,
                st.session_state.summary_record_id,
                document_key,
            )

        with history_tab:
            render_saved_summaries()
    except Exception as error:
        st.error(f"PDF를 읽는 중 오류가 발생했습니다: {error}")
else:
    st.session_state.summary_document_key = None
    st.session_state.summary_result = None
    st.session_state.summary_record_id = None
    st.session_state.quiz_result = None
    st.sidebar.info("PDF를 업로드하면 파일명과 총 페이지 수가 표시됩니다.")
    original_tab, summary_tab, quiz_tab, history_tab = st.tabs(
        ["원문", "요약", "퀴즈", "저장 기록"]
    )
    with original_tab:
        st.info("왼쪽 사이드바에서 PDF 파일을 업로드하세요.")
    with summary_tab:
        st.info("PDF를 업로드한 뒤 요약하기 버튼을 눌러주세요.")
    with quiz_tab:
        st.info("요약을 저장한 뒤 퀴즈를 생성할 수 있습니다.")
    with history_tab:
        render_saved_summaries()