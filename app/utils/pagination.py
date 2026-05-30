def pagination_params(args, default_per_page=25, max_per_page=100):
    page = max(int(args.get("page", 1)), 1)
    per_page = min(max(int(args.get("per_page", default_per_page)), 1), max_per_page)
    return page, per_page


def page_payload(pagination, items):
    return {
        "items": items,
        "page": pagination.page,
        "pages": pagination.pages,
        "per_page": pagination.per_page,
        "total": pagination.total,
    }

