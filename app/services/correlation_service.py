from app.extensions import db
import math

from app.models import Memory, MemoryAsset, MemoryCorrelation


class CorrelationService:
    GENERIC_TAGS = {
        "upload",
        "uploaded",
        "file",
        "document",
        "image",
        "visual",
        "pdf",
        "docx",
        "xlsx",
        "xlsm",
        "txt",
        "log",
        "md",
        "jpg",
        "jpeg",
        "png",
        "webp",
    }
    STOP_WORDS = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "use",
        "uses",
        "are",
        "was",
        "were",
        "uploaded",
        "upload",
        "stored",
        "path",
        "local",
        "file",
        "files",
        "image",
        "images",
        "document",
        "documents",
        "mime",
        "type",
        "bytes",
        "kept",
        "visual",
        "vector",
        "fingerprint",
        "metadata",
        "correlation",
        "profile",
        "dominant",
        "color",
        "content",
        "extractable",
        "requires",
        "original",
    }
    def correlate_memory(self, memory, limit=12):
        candidates = (
            Memory.query.filter(
                Memory.workspace_id == memory.workspace_id,
                Memory.id != memory.id,
                Memory.deleted_at.is_(None),
            )
            .order_by(Memory.created_at.desc())
            .limit(250)
            .all()
        )
        created = []
        for candidate in candidates:
            strength, reasons = self._score(memory, candidate)
            if strength < 0.25:
                continue
            source_id, target_id = sorted([memory.id, candidate.id])
            existing = MemoryCorrelation.query.filter_by(
                source_memory_id=source_id,
                target_memory_id=target_id,
                correlation_type="related",
            ).first()
            if existing:
                existing.strength = max(existing.strength, strength)
                existing.explanation = ", ".join(reasons)
                created.append(existing)
                continue
            correlation = MemoryCorrelation(
                workspace_id=memory.workspace_id,
                source_memory_id=source_id,
                target_memory_id=target_id,
                correlation_type="related",
                strength=strength,
                explanation=", ".join(reasons),
            )
            db.session.add(correlation)
            created.append(correlation)
            if len(created) >= limit:
                break
        db.session.commit()
        return created

    def rebuild_workspace(self, workspace_id):
        MemoryCorrelation.query.filter_by(workspace_id=workspace_id).delete()
        db.session.commit()
        total = 0
        for memory in Memory.query.filter_by(workspace_id=workspace_id).filter(Memory.deleted_at.is_(None)).all():
            total += len(self.correlate_memory(memory))
        return total

    def for_memory(self, memory_id):
        return MemoryCorrelation.query.filter(
            (MemoryCorrelation.source_memory_id == memory_id) | (MemoryCorrelation.target_memory_id == memory_id)
        ).order_by(MemoryCorrelation.strength.desc()).all()

    def _score(self, left, right):
        strength = 0.0
        reasons = []
        shared_tags = sorted((set(left.tags or []) & set(right.tags or [])) - self.GENERIC_TAGS)
        if shared_tags:
            strength += min(0.55, len(shared_tags) * 0.32)
            reasons.append(f"shared tags: {', '.join(shared_tags[:4])}")
        meaningful_signal = bool(shared_tags)
        if left.memory_type == right.memory_type:
            strength += 0.08
            reasons.append(f"same type: {left.memory_type}")
        if left.agent_id == right.agent_id:
            strength += 0.03
            reasons.append("same agent")
        if left.session_id and left.session_id == right.session_id:
            strength += 0.25
            reasons.append("same session")
            meaningful_signal = True
        left_words = self._keywords(left.content)
        right_words = self._keywords(right.content)
        shared_words = sorted(left_words & right_words)
        if shared_words:
            strength += min(0.25, len(shared_words) * 0.025)
            reasons.append(f"shared terms: {', '.join(shared_words[:5])}")
            meaningful_signal = True
        asset_strength, asset_reasons = self._asset_score(left, right)
        strength += asset_strength
        reasons.extend(asset_reasons)
        if asset_strength >= 0.12:
            meaningful_signal = True
        if not meaningful_signal:
            return 0.0, []
        return min(strength, 1.0), reasons or ["nearby workspace memory"]

    def _keywords(self, text):
        return {
            word.strip(".,:;!?()[]{}<>/\\|\"'").lower()
            for word in (text or "").split()
            if len(word.strip(".,:;!?()[]{}<>/\\|\"'")) > 3
            and word.strip(".,:;!?()[]{}<>/\\|\"'").lower() not in self.STOP_WORDS
            and not word.startswith("/")
        }

    def _asset_score(self, left, right):
        left_assets = MemoryAsset.query.filter_by(memory_id=left.id).all()
        right_assets = MemoryAsset.query.filter_by(memory_id=right.id).all()
        if not left_assets and not right_assets:
            return 0.0, []
        strength = 0.0
        reasons = []
        if left_assets and right_assets:
            left_types = {asset.asset_type for asset in left_assets}
            right_types = {asset.asset_type for asset in right_assets}
            shared_types = sorted(left_types & right_types)
            if shared_types:
                strength += 0.12
                reasons.append(f"shared asset type: {', '.join(shared_types)}")
            best_visual = 0.0
            for left_asset in left_assets:
                for right_asset in right_assets:
                    if left_asset.asset_type != right_asset.asset_type:
                        continue
                    similarity = self._cosine(left_asset.vector or [], right_asset.vector or [])
                    best_visual = max(best_visual, similarity)
            if best_visual >= 0.85:
                strength += 0.35
                reasons.append(f"similar asset vectors: {best_visual:.2f}")
            elif best_visual >= 0.7:
                strength += 0.2
                reasons.append(f"related asset vectors: {best_visual:.2f}")
            if not shared_types:
                metadata_terms = self._asset_metadata_terms(left_assets) & self._asset_metadata_terms(right_assets)
                if metadata_terms:
                    strength += min(0.12, len(metadata_terms) * 0.03)
                    reasons.append(f"shared asset metadata: {', '.join(sorted(metadata_terms)[:4])}")
        else:
            asset = (left_assets or right_assets)[0]
            metadata = asset.asset_metadata or {}
            terms = self._keywords(" ".join(str(value) for value in metadata.values()))
            other_words = self._keywords(right.content if left_assets else left.content)
            shared = sorted(terms & other_words)
            if shared:
                strength += min(0.18, len(shared) * 0.04)
                reasons.append(f"asset metadata matches text: {', '.join(shared[:4])}")
        return strength, reasons

    def _asset_metadata_terms(self, assets):
        terms = set()
        for asset in assets:
            metadata = asset.asset_metadata or {}
            terms |= self._keywords(" ".join(str(value) for value in metadata.values()))
        return terms

    def _cosine(self, left, right):
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
        right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)
