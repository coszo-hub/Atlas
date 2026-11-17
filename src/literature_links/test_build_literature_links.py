import json
import tempfile
import unittest
from pathlib import Path

import build_literature_links as links


def write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class LiteratureLinksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        lit, ft = self.tmp / "Literature", self.tmp / "LiteratureFullText"
        write(self.tmp / "instruments.jsonl", [
            {"canonical_id": "EARTHSCOPE-OO-HYS14", "name": "HYS14 seismometer", "instrument_type": "seismometer",
             "location": "Southern Hydrate Ridge Summit", "aliases": ["RS01SUM1-LJ01B-05-OBSBBA101"], "record_status": "catalogued_instance"},
            {"canonical_id": "EARTHSCOPE-OO-HYS13", "name": "HYS13 seismometer", "instrument_type": "seismometer",
             "location": "Southern Hydrate Ridge Summit", "aliases": [], "record_status": "catalogued_instance"},
            {"canonical_id": "RS03CCAL-MJ03F-05-BOTPTA301", "name": "Central Caldera BOTPT", "instrument_type": "pressure",
             "location": "Axial Seamount Central Caldera", "site": "RS03CCAL", "node": "MJ03F", "aliases": ["RS03CCAL-MJ03F-BOTPTA301"],
             "record_status": "catalogued_instance"},
        ])
        write(lit / "documents.jsonl", [
            {"document_id": "P-RANGE", "title": "DAS seismicity", "publication_year": 2023, "doi": "10.1/range"},
            {"document_id": "P-DESC", "title": "Methane bubbles", "publication_year": 2021, "doi": "10.1/desc"},
            {"document_id": "P-ODP", "title": "ODP Leg 204 seismics", "publication_year": 2003, "doi": "10.1/odp"},
            {"document_id": "P-BOTPT", "title": "Axial inflation", "publication_year": 2016, "doi": "10.1/botpt"},
            {"document_id": "P-OTHER", "title": "A Mid-Atlantic vent", "publication_year": 2019, "doi": "10.1/other"},
        ])
        write(lit / "chunks.jsonl", [
            {"chunk_id": "a1", "document_id": "P-ODP", "document_type": "literature_work",
             "text": "Ocean bottom seismometers deployed at Southern Hydrate Ridge during ODP Leg 204."},
            {"chunk_id": "a2", "document_id": "P-OTHER", "document_type": "literature_work",
             "text": "The Inferno vent at Lucky Strike, and a caldera nearby."},
        ])
        write(ft / "chunks.jsonl", [
            {"chunk_id": "f1", "document_id": "P-RANGE", "page": 3, "text": "We used OOI stations HYS11‐14 at the summit."},
            {"chunk_id": "f2", "document_id": "P-DESC", "page": 2,
             "text": "At the SHR summit, data from three ocean bottom seismometers (OBS) of the OOI Cabled Array were used."},
            {"chunk_id": "f3", "document_id": "P-BOTPT", "page": 5,
             "text": "The official OOI name is RS03CCAL-MJ03F-BOTPTA301; the Axial caldera inflated after the 2015 eruption."},
        ])
        self.saved = (links.LIT, links.FULLTEXT, links.INSTRUMENTS)
        links.LIT, links.FULLTEXT, links.INSTRUMENTS = lit, ft, self.tmp / "instruments.jsonl"
        links.build(self.tmp / "out")
        self.rel = [json.loads(l) for l in (self.tmp / "out/relationships.jsonl").read_text().splitlines()]
        self.edges = {(r["source_id"], r["target_id"]): r for r in self.rel if r["predicate"] != "EVIDENCE_FOR"}

    def tearDown(self):
        links.LIT, links.FULLTEXT, links.INSTRUMENTS = self.saved

    def test_a_range_names_every_station_it_takes_in(self):
        for code in ("HYS13", "HYS14"):
            link = self.edges[("P-RANGE", f"EARTHSCOPE-OO-{code}")]
            self.assertEqual((link["predicate"], link["match"], link["evidence_page"]), ("NAMES_SENSOR", ["range"], 3))

    def test_a_description_links_the_sensors_of_that_kind_at_the_site(self):
        link = self.edges[("P-DESC", "EARTHSCOPE-OO-HYS14")]
        self.assertEqual((link["predicate"], link["sensors_sharing_description"]), ("DESCRIBES_SENSOR", 2))

    def test_a_description_before_the_rca_or_without_it_links_nothing(self):
        self.assertNotIn(("P-ODP", "EARTHSCOPE-OO-HYS14"), self.edges)

    def test_a_designator_without_its_port_names_the_sensor(self):
        self.assertEqual(self.edges[("P-BOTPT", "RS03CCAL-MJ03F-05-BOTPTA301")]["match"], ["designator"])

    def test_features_axial_names_need_axial(self):
        self.assertIn(("P-BOTPT", "FEATURE-axial-eruption-2015"), self.edges)
        self.assertIn(("P-BOTPT", "FEATURE-axial-caldera"), self.edges)
        self.assertNotIn(("P-OTHER", "FEATURE-vent-inferno"), self.edges)
        self.assertNotIn(("P-OTHER", "FEATURE-axial-caldera"), self.edges)

    def test_sensor_nodes_carry_their_identities(self):
        ents = {e["entity_id"]: e for e in map(json.loads, (self.tmp / "out/entities.jsonl").read_text().splitlines())}
        self.assertIn("HYS14", ents["EARTHSCOPE-OO-HYS14"]["aliases"])
        self.assertIn("RS01SUM1-LJ01B-05-OBSBBA101", ents["EARTHSCOPE-OO-HYS14"]["aliases"])


if __name__ == "__main__":
    unittest.main()
