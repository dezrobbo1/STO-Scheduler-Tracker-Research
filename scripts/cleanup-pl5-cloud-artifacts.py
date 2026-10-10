#!/usr/bin/env python3
"""Retire historical Android gate artifacts containing raw native debug logs.

Only PL5 cloud-emulator artifacts from the existing trial branch are eligible.
No genuine-device return or other repository artifacts are touched.
"""
import json
import os
import urllib.request

REPO = 'dezrobbo1/STO-Scheduler-Tracker-Research'
BRANCH = 'feat/p2-pl5-offline-field-app'
# Audited pre-correction artifacts. Never retire future safe evidence.
UNSAFE_ARTIFACT_IDS = {11543100748, 11541818381, 11541606516, 11527950332,
                       11527460716, 11527354865, 11526078921}

def eligible(artifact, current_sha):
    run = artifact.get('workflow_run', {})
    return artifact.get('id') in UNSAFE_ARTIFACT_IDS and artifact.get('name') == 'pl5-cloud-emulator' and run.get('head_branch') == BRANCH and run.get('head_sha') != current_sha

def main():
    if os.environ['GITHUB_REPOSITORY'] != REPO:
        raise ValueError('unexpected cleanup repository')
    def request(path, method='GET'):
        req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/{path}', method=method,
            headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'], 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()
        return json.loads(content) if content else None
    candidates=[]
    page=1
    while True:
        artifacts=request(f'actions/artifacts?per_page=100&page={page}')['artifacts']
        candidates.extend(row['id'] for row in artifacts if eligible(row, os.environ['STO_BUILD_SHA']))
        if len(artifacts)<100:break
        page+=1
    for artifact_id in candidates:
        request(f'actions/artifacts/{artifact_id}', 'DELETE')
        print(f'Retired prior disposable Android log artifact {artifact_id}')

if __name__ == '__main__':main()
