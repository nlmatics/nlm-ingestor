@Library('atrix@master') _

makeBuildPipeline {
  serviceConfigurations = [
    name              : 'nlm-ingestor',
    clusterNamePrefix : 'atrix-eks-',
    helmRepo          : 'spartan',
    chartPath         : 'spartan/spartan',
    chartVersion      : '1.1.3',
    namespace         : 'service-platform'
  ]

  dockerFilePath = '/'
  dockerFileName = 'Dockerfile'

  nodeBuildLabel = 'heavy'

  helmStageTimeout = 30

  testCommand = 'jenkins-test'

  informStageEnabled = true

  codeQualityStageEnabled = false

  promoteImageEnabled = true

  devDeploymentEnabled = { ctx, buildEnv ->
      buildEnv.getBranchName() == "main" || buildEnv.getBranchName() == "master"
  }

  additionalContainerConfig = { ctx, buildEnv ->
    if (buildEnv.isPullRequestBuild()) {
      []
    } else {
      [
        kaniko: [:]
      ]
    }
  }

  helmValuesPath = { ctx, buildEnv ->
    if (buildEnv.isDevDeploymentEnabled()) {
      'k8s/dev/values.yaml'
    } else if (buildEnv.isProdDeploymentEnabled()) {
      'k8s/prod/values.yaml'
    } else {
      ctx.error 'unknown environment!! Abort!!'
    }
  }

  helmValuesPath = { ctx, buildEnv ->
    if (buildEnv.isDevDeploymentEnabled()) {
      'k8s/dev/values.yaml'
    } else if (buildEnv.isProdDeploymentEnabled()) {
      'k8s/prod/values.yaml'
    } else {
      ctx.error 'unknown environment!! Abort!!'
    }
  }
}
