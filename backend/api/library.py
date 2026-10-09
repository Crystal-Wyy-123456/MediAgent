"""临床资料库接口 —— 提供典型病历、建议问题与预问诊话术，供页面一键载入。"""

from __future__ import annotations

from fastapi import APIRouter

from ..reference_data import PRECONSULT_PERSONA, PRECONSULT_SCRIPT, SAMPLE_PIPELINE_INPUT, SAMPLE_QUESTIONS, SAMPLE_RECORDS

router = APIRouter(prefix="/api/v1/library", tags=["library"])


@router.get("/records")
async def records() -> dict:
    return {"items": [{"id": r["id"], "title": r["title"], "department": r["department"],
                       "description": r["description"], "tags": r["tags"], "text": r["text"]} for r in SAMPLE_RECORDS]}


@router.get("/questions")
async def questions() -> dict:
    return {"items": SAMPLE_QUESTIONS}


@router.get("/preconsult-script")
async def preconsult_script() -> dict:
    return {
        "persona": PRECONSULT_PERSONA,
        "scripts": PRECONSULT_SCRIPT,
        "red_flag_suggestions": [
            "胸痛得厉害，还一直冒冷汗",
            "突然胸闷伴大汗，喘不上气",
            "刚才有一阵意识模糊，差点晕过去",
        ],
    }


@router.get("/pipeline-input")
async def pipeline_input() -> dict:
    return SAMPLE_PIPELINE_INPUT
