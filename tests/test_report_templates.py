"""Tests for report template models and registry (BE-301 Step 1)."""

import pytest

from aml.services.reporting.templates import (
    FieldConstraint,
    ReportTemplate,
    TemplateRegistry,
    TemplateSection,
)


class TestTemplateSection:
    def test_creation(self):
        section = TemplateSection(
            name="Subject Details",
            description="Details about the subject of the report",
            max_words=500,
            required=True,
            guidance="Include full name, DOB, address, and account numbers.",
        )
        assert section.name == "Subject Details"
        assert section.required is True
        assert section.max_words == 500

    def test_optional_section(self):
        section = TemplateSection(
            name="Additional Notes",
            description="Any extra context",
            max_words=200,
            required=False,
            guidance="Optional supporting information.",
        )
        assert section.required is False


class TestFieldConstraint:
    def test_creation(self):
        constraint = FieldConstraint(
            field_name="subject_name",
            max_length=256,
            required=True,
            format_hint="Full legal name",
        )
        assert constraint.field_name == "subject_name"
        assert constraint.max_length == 256
        assert constraint.required is True

    def test_optional_constraint(self):
        constraint = FieldConstraint(
            field_name="notes",
            max_length=1000,
            required=False,
        )
        assert constraint.format_hint is None


class TestReportTemplate:
    def test_creation(self):
        template = ReportTemplate(
            report_type="AUSTRAC_SMR",
            sections=[
                TemplateSection(
                    name="Subject Details",
                    description="Subject info",
                    max_words=500,
                    required=True,
                    guidance="Full name, DOB, address.",
                ),
                TemplateSection(
                    name="Suspicious Activity Description",
                    description="What happened",
                    max_words=1000,
                    required=True,
                    guidance="Describe the suspicious activity.",
                ),
            ],
            field_constraints={
                "subject_name": FieldConstraint(
                    field_name="subject_name",
                    max_length=256,
                    required=True,
                ),
            },
            system_prompt_addendum="You are drafting an AUSTRAC SMR.",
        )
        assert template.report_type == "AUSTRAC_SMR"
        assert len(template.sections) == 2
        assert template.sections[0].name == "Subject Details"

    def test_required_sections(self):
        template = ReportTemplate(
            report_type="TEST",
            sections=[
                TemplateSection(name="A", description="", max_words=100, required=True, guidance=""),
                TemplateSection(name="B", description="", max_words=100, required=False, guidance=""),
                TemplateSection(name="C", description="", max_words=100, required=True, guidance=""),
            ],
            field_constraints={},
            system_prompt_addendum="",
        )
        required = template.required_section_names
        assert required == ["A", "C"]


class TestTemplateRegistry:
    def test_list_templates_returns_built_in_types(self):
        registry = TemplateRegistry()
        templates = registry.list_templates()
        assert "AUSTRAC_SMR" in templates
        assert "NZ_SAR" in templates

    def test_get_template_austrac_smr(self):
        registry = TemplateRegistry()
        template = registry.get_template("AUSTRAC_SMR")
        assert template.report_type == "AUSTRAC_SMR"
        assert len(template.sections) >= 4
        section_names = [s.name for s in template.sections]
        assert "Subject Details" in section_names
        assert "Suspicious Activity Description" in section_names
        assert "Transaction Details" in section_names
        assert "Reason for Suspicion" in section_names

    def test_get_template_nz_sar(self):
        registry = TemplateRegistry()
        template = registry.get_template("NZ_SAR")
        assert template.report_type == "NZ_SAR"
        assert len(template.sections) >= 3

    def test_get_template_unknown_raises(self):
        registry = TemplateRegistry()
        with pytest.raises(KeyError):
            registry.get_template("NONEXISTENT")

    def test_all_built_in_templates_have_required_sections(self):
        registry = TemplateRegistry()
        for report_type in registry.list_templates():
            template = registry.get_template(report_type)
            assert len(template.required_section_names) >= 1

    def test_all_built_in_templates_have_system_prompt(self):
        registry = TemplateRegistry()
        for report_type in registry.list_templates():
            template = registry.get_template(report_type)
            assert len(template.system_prompt_addendum) > 0

    def test_register_custom_template(self):
        registry = TemplateRegistry()
        custom = ReportTemplate(
            report_type="CUSTOM_REPORT",
            sections=[
                TemplateSection(name="Summary", description="", max_words=500, required=True, guidance=""),
            ],
            field_constraints={},
            system_prompt_addendum="Custom report instructions.",
        )
        registry.register(custom)
        assert "CUSTOM_REPORT" in registry.list_templates()
        assert registry.get_template("CUSTOM_REPORT").report_type == "CUSTOM_REPORT"
