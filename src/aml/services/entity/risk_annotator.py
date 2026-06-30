from aml.services.entity.models import OwnershipGraph

HIGH_RISK_JURISDICTIONS = {"IR", "KP", "SY", "CU", "MM", "AF"}


class EntityRiskAnnotator:
    def annotate(self, graph: OwnershipGraph) -> OwnershipGraph:
        flagged_count = 0

        for entity in graph.entities.values():
            if entity.jurisdiction.upper() in HIGH_RISK_JURISDICTIONS:
                entity.risk_flags.append("high_risk_jurisdiction")

            if len(entity.directors) > 0:
                dir_count = len(entity.directors)
                if dir_count == 0 and entity.entity_type == "company":
                    entity.risk_flags.append("no_directors")

            if entity.entity_type in ("trust", "partnership") and not entity.shareholders:
                entity.risk_flags.append("shell_company_indicators")

            if entity.risk_flags:
                flagged_count += 1

        depth = len(graph.entities)
        if depth > 3:
            for entity in graph.entities.values():
                if "complex_structure" not in entity.risk_flags:
                    entity.risk_flags.append("complex_structure")

        graph.risk_summary = {
            "total_entities": len(graph.entities),
            "flagged_entities": flagged_count,
            "ubo_count": len(graph.ubos),
            "max_depth": graph.max_depth_reached,
        }

        return graph
