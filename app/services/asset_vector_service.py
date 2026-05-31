import math
from pathlib import Path

from app.utils.hash import sha256_bytes, sha256_json


class AssetVectorService:
    def image_vector(self, path):
        try:
            from PIL import Image, ImageStat
        except Exception:
            return self._byte_vector(path)

        try:
            image = Image.open(path).convert("RGB")
            width, height = image.size
            thumb = image.resize((64, 64))
            hist = thumb.histogram()
            bins = []
            for channel in range(3):
                channel_hist = hist[channel * 256 : (channel + 1) * 256]
                total = sum(channel_hist) or 1
                for start in range(0, 256, 32):
                    bins.append(sum(channel_hist[start : start + 32]) / total)
            stat = ImageStat.Stat(thumb)
            features = bins + [value / 255 for value in stat.mean] + [value / 255 for value in stat.stddev]
            features.extend([min(width / 4096, 1), min(height / 4096, 1), min(width / max(height, 1), 4) / 4])
            vector = self._fit(features, 384)
            metadata = {
                "width": width,
                "height": height,
                "mean_rgb": [round(value, 2) for value in stat.mean],
                "dominant_color": self._dominant_color(stat.mean),
                "vector_kind": "image_color_histogram",
            }
            return vector, sha256_json([round(float(x), 6) for x in vector]), metadata
        except Exception:
            return self._byte_vector(path)

    def document_vector(self, text, path):
        words = [word.strip(".,:;!?()[]{}").lower() for word in text.split() if len(word) > 2]
        buckets = [0.0] * 384
        for word in words[:5000]:
            buckets[abs(hash(word)) % 384] += 1.0
        vector = self._normalize(buckets)
        metadata = {
            "filename": Path(path).name,
            "word_count": len(words),
            "vector_kind": "document_keyword_hash",
        }
        return vector, sha256_json([round(float(x), 6) for x in vector]), metadata

    def _byte_vector(self, path):
        data = Path(path).read_bytes()
        buckets = [0.0] * 384
        for index, byte in enumerate(data[:65536]):
            buckets[index % 384] += byte / 255
        vector = self._normalize(buckets)
        metadata = {
            "filename": Path(path).name,
            "size_bytes": len(data),
            "vector_kind": "file_byte_fingerprint",
        }
        return vector, sha256_bytes(data), metadata

    def _fit(self, values, size):
        fitted = list(values)
        while len(fitted) < size:
            fitted.extend(values)
        return self._normalize(fitted[:size])

    def _normalize(self, values):
        norm = math.sqrt(sum(value * value for value in values))
        if not norm:
            return values
        return [float(value / norm) for value in values]

    def _dominant_color(self, mean):
        red, green, blue = mean
        if max(mean) < 50:
            return "dark"
        if min(mean) > 205:
            return "light"
        if red >= green and red >= blue:
            return "red"
        if green >= red and green >= blue:
            return "green"
        return "blue"
