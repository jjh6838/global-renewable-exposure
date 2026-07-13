# To ssh OUCE cluster from VS code

Open VS Code and press Ctrl+Shift+P.
Select Remote-SSH: Connect to Host…
Choose:
ouce-hn02.ouce.ox.ac.uk
Enter your cluster password if requested.
Open:
/home/lina4376/dphil_p2/p2_test

OR?
(p1_etl) PS Z:\dphil_p2\p2_test> ssh lina4376@ouce-hn02.ouce.ox.ac.uk

# Within OUCE cluster, you can do git directly as git is authenticated in OUCE cluster. 
# However, Within VS code, after ssh OUCE cluster, you need to check whether git is possible or not. There was an issue on the cluster side (no tmp file space for the time being)

# p2_test: Country Exposure Run (Slurm)

## Submit job
```bash
sbatch /soge-home/users/lina4376/dphil_p2/p2_test/process_country_exposure.sh
```

## Submit selected-country hazard extract job
```bash
sbatch /soge-home/users/lina4376/dphil_p2/p2_test/process_country_hazard_extract.sh
```

## If sbatch reports DOS line breaks
```bash
sed -i 's/\r$//' /soge-home/users/lina4376/dphil_p2/p2_test/process_country_exposure.sh
sed -i 's/\r$//' /soge-home/users/lina4376/dphil_p2/p2_test/process_country_hazard_extract.sh
```

## Check progress
```bash
# queue/running status
squeue -j <JOB_ID>

# detailed state
scontrol show job <JOB_ID>

# live log output
tail -f /soge-home/users/lina4376/dphil_p2/p2_test/output_global/slurm_country_exposure_<JOB_ID>.out
```

## Check final job result
```bash
sacct -j <JOB_ID> --format=JobID,State,Elapsed,MaxRSS,ExitCode
```

## Main output paths
- Country parquet outputs:  
  `/soge-home/users/lina4376/dphil_p2/p2_test/output_per_country/parquet_exposure`
- Global GPKG:  
  `/soge-home/users/lina4376/dphil_p2/p2_test/output_global/polylines_global_exposure.gpkg`
- Excel summary:  
  `/soge-home/users/lina4376/dphil_p2/p2_test/output_global/polylines_global_exposure_summary.xlsx`
