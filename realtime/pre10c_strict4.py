"""Run the isolated strict-4 pre-test profile without changing the default service."""
import argparse,asyncio
from .pre10c_config import PROFILE_NAME,SOLVE_DFS,activate

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration",type=float)
    parser.add_argument("--api-port",type=int,default=8090)
    parser.add_argument("--publish-df17-mlat",action="store_true")
    args=parser.parse_args()
    stations,order=activate()
    from .localization import configure_solver_geometry
    configure_solver_geometry(stations,order)
    from .main import run
    asyncio.run(run(args.duration,args.api_port,args.publish_df17_mlat,SOLVE_DFS,PROFILE_NAME))

if __name__=="__main__":main()
