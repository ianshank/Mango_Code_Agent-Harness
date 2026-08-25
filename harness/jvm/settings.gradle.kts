import org.gradle.api.initialization.resolve.RepositoriesMode
rootProject.name = "agentic-ssd-governance-jvm-template"
pluginManagement { repositories { gradlePluginPortal(); mavenCentral() } }
dependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { mavenCentral() } }
