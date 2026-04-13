import coverage  # type: ignore

cov = coverage.Coverage(data_file='.coverage')
try:
    cov.load()
    data = cov.get_data()
    files = list(data.measured_files())
    print('measured files:', len(files))
    for f in files[:200]:
        print('-', f)
except Exception as e:
    print('error loading coverage:', e)
