import os
import glob
from typing import Optional


def run_all(files: Optional[list[str]] = None):
    os.chdir("../../tutorials")
    failed = False
    failed_files = []
    if files is None:
        files = glob.glob("*.ipynb")
    for file in files:
        new_file = file[:-6] + ".py"
        cmd_convert = "jupyter nbconvert --to script " + file
        os.system(cmd_convert)
        remove_plots(new_file)

        cmd_run = "python " + str(new_file)
        status = os.system(cmd_run)
        if status != 0:
            print("\n")
            print("*********************\n")
            print(file + " failed\n\n")
            print("********************\n")
            failed = True
            failed_files.append(file)
        os.remove(new_file)
    if not failed:
        print("********************\n")
        print("All tutorials ran. \n")
        print("********************\n")
    else:
        print("********************\n")
        print("The following tutorials failed: \n")
        print(*failed_files, sep=", ")
        print("********************\n")
    assert not failed


def remove_plots(fn):
    with open(fn) as f:
        content = f.readlines()

    with open(fn, "w") as f:
        for line in content:
            if line.strip()[:9] == "plot_grid":
                continue
            if line.strip()[:12] == "pp.plot_grid":
                continue
            if line.strip()[:4] == "plt.":
                continue
            if line.strip()[:17] == "pp.plot_fractures":
                continue
            if line.strip()[:11] == "get_ipython":
                continue
            if line.strip()[:15] == "network_2d.plot":
                continue
            if line.strip()[:6] == "print(":
                continue
            if "vtk" in line:
                continue
            if "Exporter" in line:
                continue
            if "exporter" in line:
                continue
            if "write" in line:
                continue
            if "import plot_grid" in line:
                continue
            f.write(line)


if __name__ == "__main__":
    run_all()
