from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class SkillManager:
    """Filesystem-backed reusable operating procedures and domain skill packs."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir.resolve()
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, skill_id: str) -> Path:
        if not _SAFE_ID.fullmatch(skill_id):
            raise ValueError("Skill id must contain lowercase letters, numbers, hyphens, or underscores")
        return self.skills_dir / f"{skill_id}.json"

    def list(self) -> dict[str, Any]:
        skills = []
        for path in sorted(self.skills_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("id", path.stem)
                    data["path"] = str(path)
                    skills.append(data)
            except Exception:
                skills.append({"id": path.stem, "name": path.stem, "error": "Invalid skill JSON", "path": str(path)})
        return {"ok": True, "skills": skills}

    def get(self, skill_id: str) -> dict[str, Any]:
        path = self._path(skill_id)
        if not path.exists():
            return {"ok": False, "error": "Skill not found"}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"ok": True, "skill": data}

    def create(self, skill_id: str, name: str, description: str, instructions: str,
               examples: list[str] | None = None, allowed_tools: list[str] | None = None,
               overwrite: bool = False) -> dict[str, Any]:
        path = self._path(skill_id)
        if path.exists() and not overwrite:
            return {"ok": False, "error": "Skill already exists"}
        payload = {
            "id": skill_id,
            "name": name.strip() or skill_id,
            "description": description.strip(),
            "instructions": instructions.strip(),
            "examples": examples or [],
            "allowed_tools": allowed_tools or [],
            "version": 1,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "skill": payload, "path": str(path)}

    def context(self, skill_ids: list[str] | None, max_chars: int = 40_000) -> str:
        parts: list[str] = []
        total = 0
        for skill_id in (skill_ids or [])[:8]:
            result = self.get(skill_id)
            if not result.get("ok"):
                continue
            skill = result["skill"]
            block = (
                f"Skill: {skill.get('name', skill_id)} ({skill_id})\n"
                f"Purpose: {skill.get('description', '')}\n"
                f"Operating instructions:\n{skill.get('instructions', '')}"
            )
            if total + len(block) > max_chars:
                break
            parts.append(block)
            total += len(block)
        return "\n\n".join(parts)