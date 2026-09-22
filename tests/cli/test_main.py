from elsevier_coordinate_extraction.cli.main import create_parser


def test_parser_continues_on_error_by_default():
    parser = create_parser()
    args = parser.parse_args(["--pmids", "12345678"])
    assert args.continue_on_error is True


def test_parser_fail_fast_overrides_continue_behavior():
    parser = create_parser()
    args = parser.parse_args(["--pmids", "12345678", "--fail-fast"])
    assert args.continue_on_error is False
