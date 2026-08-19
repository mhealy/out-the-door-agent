import re
from typing import Protocol

from app.domain.criteria import CriteriaExtractionResult, VehicleSearchCriteria


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
            r"(?:\bnear\b|\baround\b|\bin\b|\bof\b)\s+"
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
        if required_feature_phrase and not re.search(
            r"\b(?:awd|panoramic roof|heated seats)\b",
            required_feature_phrase.group(1),
        ):
            raise UnsupportedCriteriaError(
                "The fixture interpreter cannot represent the explicitly required "
                f"feature '{required_feature_phrase.group(1).strip()}'."
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
            for keyword, feature in (
                ("awd", "AWD"),
                ("panoramic roof", "panoramic roof"),
                ("heated seats", "heated seats"),
            )
            if required_feature_phrase
            and re.search(rf"\b{keyword}\b", required_feature_phrase.group(1))
        ]
        excluded_features = [
            feature
            for feature in ("panoramic roof", "sunroof", "damage")
            if re.search(rf"\b(?:avoid|no|exclude)\b[^.]*\b{feature}\b", lowered)
        ]
        preferred_colors = [
            color.title()
            for color in ("blue", "white", "gray", "silver", "red")
            if re.search(rf"\bprefer\w*\b.*\b{color}\b", lowered)
        ]
        excluded_exterior_colors = [
            color.title()
            for color in ("black", "white", "gray", "silver", "red")
            if re.search(
                rf"\b(?:avoid|no|exclude)\b[^.]*\b{color}\b(?:\s+exterior)?", lowered
            )
            and not re.search(rf"\b{color}\s+interior\b", lowered)
        ]
        excluded_interior_colors = [
            color.title()
            for color in ("black", "white", "gray", "silver", "red")
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

        criteria = VehicleSearchCriteria(
            make="Hyundai",
            model="Tucson Hybrid",
            trims=trims,
            condition=(
                "either"
                if ("new" in lowered and "used" in lowered)
                or ("new" not in lowered and "used" not in lowered)
                else "used"
                if "used" in lowered
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
