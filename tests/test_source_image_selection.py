import unittest

from prism.agents import _upstream_context
from prism.models import RESOURCE_PRESENTATION


class SourceImageSelectionTests(unittest.TestCase):
    def test_only_human_selected_document_images_reach_resource_context(self) -> None:
        state = {
            "course": {"unit_name": "UC", "taxonomy_type": "SOLO"},
            "feedback": {},
            "resource_types": [RESOURCE_PRESENTATION],
            "selected_source_image_ids": ["document-selected"],
            "source_images": [
                {
                    "id": "document-selected",
                    "source_file": "apoio.pdf",
                    "source_location": "Página 2",
                    "filename": "figura.png",
                    "media_type": "image/png",
                    "candidate_kind": "composite_render",
                    "width_px": 900,
                    "height_px": 500,
                },
                {
                    "id": "document-not-selected",
                    "source_file": "apoio.pdf",
                    "source_location": "Página 4",
                    "filename": "outra.png",
                    "media_type": "image/png",
                    "candidate_kind": "embedded",
                    "width_px": 800,
                    "height_px": 600,
                },
            ],
            "ai_image_generation_enabled": False,
        }

        context = _upstream_context(state, "resources")

        catalogue = context["source_image_catalogue"]
        self.assertEqual(len(catalogue), 1)
        self.assertEqual(catalogue[0]["id"], "document-selected")
        self.assertEqual(catalogue[0]["candidate_kind"], "composite_render")


if __name__ == "__main__":
    unittest.main()
