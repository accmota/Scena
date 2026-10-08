import cProfile
import pstats
import io
import sys
import importlib.util

def profile_script(script_path, sort_by='cumulative', lines_to_show=20):
    """
    Profile a Scena framework script.
    
    Args:
        script_path: Path to the script to profile
        sort_by: Sorting method for results ('cumulative', 'time', 'calls', etc.)
        lines_to_show: Number of results to display
    """
    # Create a profile object
    profiler = cProfile.Profile()
    
    # Load the script as a module
    spec = importlib.util.spec_from_file_location("module_to_profile", script_path)
    module = importlib.util.module_from_spec(spec)
    
    # Start profiling and run the module
    profiler.enable()
    spec.loader.exec_module(module)
    profiler.disable()
    
    # Print results
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats(sort_by)
    ps.print_stats(lines_to_show)
    print(s.getvalue())
    
    # Optionally save results to a file
    with open(f"{script_path}_profile_results.txt", "w") as f:
        ps = pstats.Stats(profiler, stream=f).sort_stats(sort_by)
        ps.print_stats()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/tools/profile_scena.py <path_to_script> [sort_by] [lines_to_show]")
        sys.exit(1)
    
    script_path = sys.argv[1]
    sort_by = sys.argv[2] if len(sys.argv) > 2 else 'cumulative'
    lines_to_show = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    
    profile_script(script_path, sort_by, lines_to_show) 