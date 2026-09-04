from datetime import timedelta
import re

import news_shadow_v5_4 as v54


class CyrusNewsAdapter:
    def snapshot(self, symbol: str):
        cutoff = v54.now() - timedelta(hours=v54.LOOKBACK_HOURS)

        articles = []
        feed_status = []

        for src, url, rel in v54.FEEDS:
            try:
                blob = v54.fetch(url)
                rows = [
                    a for a in v54.parse_feed(src, rel, blob)
                    if a.get("published") and a["published"] >= cutoff
                ]
                articles.extend(rows)
                feed_status.append((src, "OK", len(rows)))
            except Exception:
                feed_status.append((src, "ERROR", 0))

        ded = {}
        for a in articles:
            k = re.sub(r"\W+", " ", (a.get("title") or "").lower()).strip()
            if k not in ded or a.get("rel", 0) > ded[k].get("rel", 0):
                ded[k] = a
        articles = list(ded.values())

        market_events = []
        for a in articles:
            s = v54.impact(a)
            w = a.get("rel", 0) * v54.fresh(a.get("published"))
            if w and v54.globalnews(a) and abs(s) > 0:
                market_events.append((s, w, a))

        market_score, market_conf = v54.aggregate(market_events)

        symbol_events = []
        emergency = False

        for a in articles:
            rel = v54.symbol_relevance(a, symbol)
            if rel < 0.55:
                continue

            s = v54.impact(a)
            w = a.get("rel", 0) * v54.fresh(a.get("published")) * rel

            if w and abs(s) > 0:
                symbol_events.append((s, w, a))

            if v54.article_emergency(a, symbol, s, rel):
                emergency = True

        symbol_score, symbol_conf = v54.aggregate(symbol_events)

        # Prefer symbol-specific signal when meaningful; otherwise use market backdrop.
        if symbol_conf >= 0.18:
            score = symbol_score
            confidence = symbol_conf
        else:
            score = market_score
            confidence = market_conf

        return {
            "score": score,
            "confidence": confidence,
            "verdict": v54.verdict(score, confidence),
            "emergency": emergency,
            "symbol_score": symbol_score,
            "symbol_confidence": symbol_conf,
            "market_score": market_score,
            "market_confidence": market_conf,
            "feed_status": feed_status,
        }


if __name__ == "__main__":
    print("V7 NEWS ADAPTER IMPORT OK")
