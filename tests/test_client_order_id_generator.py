from stock_platform.order.id_generator import ClientOrderIdGenerator

def test_unique_ids():
    a = ClientOrderIdGenerator.generate()
    b = ClientOrderIdGenerator.generate()
    assert a.startswith("ORD-")
    assert a != b
    assert len(a) <= 50
