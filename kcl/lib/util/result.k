# Format the result that matches the Telescope ADX schema.
formatResult = lambda resultJson: str -> str {
    """
{
  "timestamp": "\${TIMESTAMP}",
  "run_id": "$(RUN_ID)",
  "run_url": "$(System.TeamFoundationCollectionUri)$(System.TeamProject)/_build/results?buildId=$(Build.BuildId)",
  "pipeline": "$(Build.DefinitionName)",
  "result": ${resultJson}
}"""
}
