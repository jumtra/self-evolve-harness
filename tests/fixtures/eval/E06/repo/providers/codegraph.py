class CodeGraphProvider:
    def find_symbol(self, name):
        return {"status": "OK", "results": [name]}

    def callers(self, name):
        return {"status": "OK", "results": []}
