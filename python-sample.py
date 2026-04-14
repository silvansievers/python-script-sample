#! /usr/bin/env python3

import argparse
import logging
from pathlib import Path
import subprocess
import sys
import xmlschema


output = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
path = output.stdout.rstrip("\n")
REPO_ROOT = Path(path)
assert REPO_ROOT.is_dir()
ALLG_DIR = REPO_ROOT.parent / "allg"
XSD_FILES = [
    "TODO",
]
INDENTATION_WIDTH = 3
DESCRIPTION="""
This tool parses redacted XSD files in
shared drive redacted, which
have to be put next to this repository. It then proceeds to find the
top-level XSD components corresponding to each of the given tags and
creates a C++ class designed for use in
redacted of the server
repository."""

def update_type_to_doc(
    component: xmlschema.validators.simple_types.XsdAtomicRestriction,
    type_to_doc: dict) -> None:
    # we use local_name because name is the full name including namespace
    doc_string = f"{component.base_type.local_name} (possible values: {component.enumeration})"
    logging.info(f"Updating type_to_doc with {component.name} -> {doc_string}")
    type_to_doc[component.name] = doc_string


def get_doc_lines_from_annotation(
    annotation: xmlschema.validators.xsdbase.XsdAnnotation) -> list:
    lines = []
    for child in annotation.documentation:
        child_lines = child.text.splitlines() # doc contains new lines
        lines.extend(child_lines)
    return lines


def get_indentation(indentation_lvl: int) -> str:
    return " " * INDENTATION_WIDTH * indentation_lvl


def get_cpp_doc_lines(doc_lines: list, indentation_lvl: int) -> list:
    lines = []
    if len(doc_lines) == 1:
        lines.append(f"{get_indentation(indentation_lvl)}// {doc_lines[0]}")
    else:
        lines.append(f"{get_indentation(indentation_lvl)}/**")
        for line in doc_lines:
            lines.append(f"{get_indentation(indentation_lvl)} * {line}")
        lines.append(f"{get_indentation(indentation_lvl)} */")
    return lines


def get_cpp_line(name: str, indentation_lvl: int) -> str:
    return f'{get_indentation(indentation_lvl)}static constexpr const char *{name} = "{name}";'


def create_class_for_xsd_component(
    global_component: xmlschema.validators.xsdbase.XsdComponent,
    output_dir: Path,
    type_to_doc: dict) -> None:
    if logging.root.isEnabledFor(logging.DEBUG):
        print("")
    logging.info(f"Creating C++ class for global XSD component {global_component}")
    class_name = global_component.name
    assert class_name is not None

    lines = []
    lines.append(f"#ifndef HEADER_GUARD_{class_name.upper()}_H_")
    lines.append(f"#define HEADER_GUARD_{class_name.upper()}_H_")
    lines.append("")

    lines.append("// Generated from xsd files")
    lines.append("")

    if global_component.annotation is not None:
        logging.debug("global component has documentation:")
        print(global_component.annotation)
        lines.extend(get_cpp_doc_lines(get_doc_lines_from_annotation(global_component.annotation), indentation_lvl=0))

    lines.append(f"class {class_name}XML {{")
    lines.append(" public:")

    first = True
    for component in global_component.iter_components():
        name = component.name
        if first:
            assert name == class_name
            lines.append(get_cpp_line(name, indentation_lvl=1))
            first = False
            continue
        logging.debug(f"global component: {component}")

        doc = []
        if isinstance(component, xmlschema.validators.groups.XsdGroup):
            logging.debug(f"component is a group with model {component.model}")
            if component.ref is not None:
                logging.debug("component group refers to {component.ref}")
            logging.debug("skipping")
            continue
        elif isinstance(component, xmlschema.validators.complex_types.XsdComplexType):
            logging.debug(f"component is a complex type with content {component.content}")
            logging.debug("skipping")
            continue
        elif isinstance(component, xmlschema.XsdElement):
            logging.debug(f"component is an element with type {component.type}")
            # we use local_name because name is the full name including namespace
            if component.type.local_name in type_to_doc:
                ref_name = type_to_doc[component.type.local_name]
            else:
                ref_name = component.type.local_name
            doc.append(f"type={ref_name}, occurs=[{component.min_occurs}, {component.max_occurs}]")
        else:
            sys.exit(f"unhandled component type {type(component)}")
        assert name is not None

        if component.annotation is not None:
            logging.debug(f"component has documentation {component.annotation}")
            doc.extend(get_doc_lines_from_annotation(component.annotation))

        if doc:
            lines.extend(get_cpp_doc_lines(doc, indentation_lvl=1))

        lines.append(get_cpp_line(name, indentation_lvl=1))

    lines.append("};")
    lines.append("")
    lines.append("#endif")
    lines.append("")
    with open(output_dir / f"{class_name}.h", "w") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog=f"./{Path(__file__).name}",
        description=DESCRIPTION)
    parser.add_argument("output_dir", help="non-existing output directory", type=Path)
    parser.add_argument("--tags", help="list of tags for which a class should be created", nargs='+', required=True)
    parser.add_argument("--log", choices=['debug', 'info', 'warning', 'error', 'critical'], help="logging level", default="warning", type=str)
    args = parser.parse_args()
    output_dir = args.output_dir
    tags = args.tags
    logging.basicConfig(format='%(levelname)s: %(message)s', level=args.log.upper())
    if not ALLG_DIR.exists():
        sys.exit(f"could not find directory {ALLG_DIR} which should reside next to the repository of this script")
    for xsd_file in XSD_FILES:
        if not xsd_file.exists():
            sys.exit(f"could not find XSD file {xsd_file}")
    if output_dir.exists():
        sys.exit(f"output directory {output_dir} already exists")

    logging.info(f"reading XSD files {XSD_FILES}")
    data_schema = xmlschema.XMLSchema(XSD_FILES)
    logging.info("done reading XSD files")
    found_components = []
    found_tags = set()
    for global_component in data_schema.iter_globals():
        """
        XsdComponent has name, local_name, qualified_name, and prefixed_name.
        In the case of our xsd files, they are all the same.
        """
        if global_component.name in tags:
            found_components.append(global_component)
            found_tags.add(global_component.name)

    if set(tags) != found_tags:
        sys.exit(f"only found components for tags {found_tags}, missing {set(tags) - found_tags}")
    logging.info("found components:")
    for component in found_components:
        logging.info(f"{component} of type {type(component)}")

    type_to_doc = {}
    Path(output_dir).mkdir()
    for component in found_components:
        if type(component) == xmlschema.validators.simple_types.XsdAtomicRestriction:
            update_type_to_doc(component, type_to_doc)
        else:
            create_class_for_xsd_component(component, output_dir, type_to_doc)


if __name__ == '__main__':
    main()
