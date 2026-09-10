#!/bin/bash

for i in {1..5}
do 
	echo "TESTING RUN # $i"
	python3 -m scenarios run-all
done
