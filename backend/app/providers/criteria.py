import re
from typing import Protocol

from app.domain.criteria import CriteriaExtractionResult, VehicleSearchCriteria


SUPPORTED_REQUIRED_FEATURES = (
    ("panoramic roof", "panoramic roof"),
    ("heated seats", "heated seats"),
    ("awd", "AWD"),
)
SUPPORTED_EXCLUDED_FEATURES = (
    ("panoramic roof", "panoramic roof"),
    ("heated seats", "heated seats"),
    ("sunroof", "sunroof"),
    ("damage", "damage"),
    ("awd", "AWD"),
)
SUPPORTED_EXCLUDED_COLORS = ("black", "white", "gray", "silver", "red")


def _unsupported_expression_text(expression: str, supported_terms: tuple[str, ...]) -> str:
    remaining = expression
    for term in sorted(supported_terms, key=len, reverse=True):
        remaining = re.sub(rf"\b{re.escape(term)}\b", " ", remaining)
    remaining = re.sub(
        r"\b(?:and|or|a|an|the|exterior|interior|cars?|colors?)\b",
        " ",
        remaining,
    )
    return " ".join(remaining.split()).strip(" -")


class CriteriaInterpreter(Protocol):
    async def interpret(self, goal: str) -> CriteriaExtractionResult: ...


class UnsupportedCriteriaError(ValueError):
    """The narrow fixture interpreter cannot represent the requested intent."""


class FixtureCriteriaInterpreter:
    """Demo interpreter for the fixture inventory scenario.

    The boundary can be replaced by an LLM-backed interpreter without changing the
    API or deterministic inventory services.
    """

    async def interpret(self, goal: str) -> CriteriaExtractionResult:
        lowered = goal.casefold()
        if not re.search(r"\btucson\s+hybrid\b", lowered):
            raise UnsupportedCriteriaError(
                "The fixture interpreter supports only Hyundai Tucson Hybrid searches; "
                "the requested make/model was unsupported or ambiguous."
            )

        explicit_make = re.search(r"\b([a-z]+)\s+tucson\s+hybrid\b", lowered)
        non_make_words = {"a", "the", "find", "want", "new", "used", "either", "my"}
        if explicit_make and explicit_make.group(1) not in {"hyundai", *non_make_words}:
            raise UnsupportedCriteriaError(
                "The fixture interpreter supports only Hyundai Tucson Hybrid searches; "
                f"make '{explicit_make.group(1).title()}' is unsupported."
            )

        location = re.search(
            r"(?:\bnear\b|\baround\b|\bin\b|\bof\b|\bfrom\b)\s+"
            r"(.+?)(?=\s+(?:under|below|within|with|and|for)\b|[.!?]|$)",
            lowered,
        )
        requested_location = location.group(1).strip(" ,") if location else None
        if requested_location:
            requested_location = re.sub(r"^(?:the\s+)?", "", requested_location)
            requested_location = re.sub(r"\s+area$", "", requested_location)
            if "houston" not in requested_location:
                raise UnsupportedCriteriaError(
                    "The fixture inventory supports only the Houston area; "
                    f"location '{requested_location.title()}' is unsupported."
                )

        if re.search(r"\b(?:lease|leasing)\b", lowered):
            raise UnsupportedCriteriaError(
                "The fixture interpreter does not support lease semantics."
            )

        required_feature_phrase = re.search(
            r"\b(?:require|must have)\b\s+([^.,;]+)", lowered
        )
        if required_feature_phrase:
            unsupported_required = _unsupported_expression_text(
                required_feature_phrase.group(1),
                tuple(keyword for keyword, _ in SUPPORTED_REQUIRED_FEATURES),
            )
            if unsupported_required:
                raise UnsupportedCriteriaError(
                    "The fixture interpreter cannot represent the explicitly required "
                    f"feature '{unsupported_required}'."
                )

        exclusion_phrases = re.findall(
            r"\b(?:avoid|exclude|no)\b\s+([^.,;]+)", lowered
        )
        supported_exclusions = (
            *(keyword for keyword, _ in SUPPORTED_EXCLUDED_FEATURES),
            *SUPPORTED_EXCLUDED_COLORS,
        )
        for exclusion_phrase in exclusion_phrases:
            unsupported_exclusion = _unsupported_expression_text(
                exclusion_phrase, supported_exclusions
            )
            if unsupported_exclusion:
                raise UnsupportedCriteriaError(
                    "The fixture interpreter cannot represent the explicit exclusion "
                    f"'{unsupported_exclusion}'."
                )

        years = [int(value) for value in re.findall(r"\b20\d{2}\b", goal)]
        distance = re.search(r"(?:within|under)\s+(\d+)\s+miles?", lowered)
        price = re.search(r"(?:under|below|max(?:imum)?)\s+\$([\d,]+)", lowered)
        trims = [
            trim
            for keyword, trim in (
                ("limited", "Limited"),
                ("sel convenience", "SEL Convenience"),
                ("sel", "SEL"),
            )
            if re.search(rf"\b{keyword}\b", lowered)
        ]
        if re.search(r"\btucson\s+hybrid\s+blue\b", lowered):
            trims.append("Blue")
        if "SEL Convenience" in trims and "SEL" in trims:
            trims.remove("SEL")
        required_features = [
            feature
            for keyword, feature in SUPPORTED_REQUIRED_FEATURES
            if required_feature_phrase
            and re.search(rf"\b{keyword}\b", required_feature_phrase.group(1))
        ]
        excluded_features = [
            feature
            for keyword, feature in SUPPORTED_EXCLUDED_FEATURES
            if re.search(rf"\b(?:avoid|no|exclude)\b[^.]*\b{keyword}\b", lowered)
        ]
        preferred_colors = [
            color.title()
            for color in ("blue", "white", "gray", "silver", "red")
            if re.search(rf"\bprefer\w*\b.*\b{color}\b", lowered)
        ]
        excluded_exterior_colors = [
            color.title()
            for color in SUPPORTED_EXCLUDED_COLORS
            if re.search(
                rf"\b(?:avoid|no|exclude)\b[^.]*\b{color}\b(?:\s+exterior)?", lowered
            )
            and not re.search(rf"\b{color}\s+interior\b", lowered)
        ]
        excluded_interior_colors = [
            color.title()
            for color in SUPPORTED_EXCLUDED_COLORS
            if re.search(rf"\b{color}\s+interior\b", lowered)
        ]
        assumptions: list[str] = []
        ambiguities: list[str] = []
        if "hyundai" not in lowered:
            assumptions.append("Interpreted Tucson Hybrid as the Hyundai model.")
        if not requested_location:
            assumptions.append(
                "Using Houston, TX because the fixture inventory is Houston-based."
            )
        if not distance:
            assumptions.append("Using a 50-mile Houston-area search radius.")
        if not years:
            assumptions.append("Model year is not restricted.")
        if not price:
            assumptions.append("No advertised-price ceiling was specified.")
        if not trims:
            ambiguities.append("No trim was specified; all trims remain eligible.")

        requests_new = bool(re.search(r"\bnew\b", lowered))
        requests_used = bool(re.search(r"\bused\b", lowered))

        criteria = VehicleSearchCriteria(
            make="Hyundai",
            model="Tucson Hybrid",
            trims=trims,
            condition=(
                "either"
                if (requests_new and requests_used)
                or (not requests_new and not requests_used)
                else "used"
                if requests_used
                else "new"
            ),
            years=years,
            home_location="Houston, TX",
            max_distance_miles=int(distance.group(1)) if distance else 50,
            max_advertised_price=price.group(1).replace(",", "") if price else None,
            required_features=required_features,
            excluded_features=excluded_features,
            preferred_exterior_colors=preferred_colors,
            excluded_exterior_colors=excluded_exterior_colors,
            excluded_interior_colors=excluded_interior_colors,
        )
        return CriteriaExtractionResult(
            criteria=criteria,
            assumptions=assumptions,
            unresolved_ambiguities=ambiguities,
        )
