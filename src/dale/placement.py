"""Version-aware placement intent stored as PNG metadata, not a Foundry document."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Placement:
    foundry_major: int = 14
    elevation_ft: int = 5

    def __post_init__(self):
        if self.foundry_major not in (13, 14):
            raise ValueError("Choose Foundry 13 or 14.")
        if type(self.elevation_ft) is not int or abs(self.elevation_ft) > 1_000_000:
            raise ValueError("Elevation must be a whole number between -1000000 and 1000000 ft.")

    @property
    def guidance(self) -> str:
        if self.foundry_major == 13:
            return (
                f"Foundry 13: place the PNG as a tile at {self.elevation_ft} ft. "
                "Floor visibility depends on the scene's module configuration."
            )
        return (
            f"Foundry 14: assign the PNG to the intended Scene Level at "
            f"{self.elevation_ft} ft and configure its elevation range/visibility."
        )

    def metadata(self) -> dict[str, str]:
        return {
            "DALE.FoundryMajor": str(self.foundry_major),
            "DALE.ElevationFeet": str(self.elevation_ft),
            "DALE.Placement": self.guidance,
            "DALE.Note": "Placement intent only; Foundry does not auto-apply PNG metadata.",
        }
