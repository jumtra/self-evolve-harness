class NoneProvider:
    def find_symbol(self, name):
        return {"status": "UNSUPPORTED", "results": []}
