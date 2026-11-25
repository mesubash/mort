# mort

mort holds on to every long job you start (training runs, data jobs, scrapers, remote scripts, hosted notebooks) and tells you when one dies, stalls or finishes.

Status: in planning. See [docs/PLAN.md](docs/PLAN.md) for the design and the phases.

```
$ mort run --name train --lock -- python train.py
$ mort track ssh my-server /jobs/prep/STATUS
$ mort track kaggle user/my-kernel --pull runs/
$ mort
JOBS
 x train         local   died 02:14 (exit 1)
 * prep          ssh     running 3h10m   STATUS: step 8/20
 ok my-kernel    kaggle  done 14:05      output pulled to runs/
MACHINE
   swap 1.1/8 GB   disk 38 GB free   lock: free
```

## License

MIT
