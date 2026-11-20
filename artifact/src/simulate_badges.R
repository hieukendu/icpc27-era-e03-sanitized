#!/usr/bin/env Rscript
# Design sensitivity only. No participant observations or recruitment recommendation.
suppressPackageStartupMessages(library(lme4))
args <- commandArgs(trailingOnly=TRUE)
reps <- if(length(args)) as.integer(args[1]) else 1000L
cores <- if(length(args)>1) as.integer(args[2]) else 6L
out <- "results/revision/simulation"
dir.create(out, recursive=TRUE, showWarnings=FALSE)
grid <- expand.grid(n=c(36L,72L,108L,144L,216L), OR=c(1,1.3,1.65,2.2),
                    heterogeneity=c("low","central","high"), stringsAsFactors=FALSE)
# Three balanced blocks: 4 true + 4 false each. Analysis uses false items;
# all 24 items are distinct within a participant and rotate across interfaces.
allocation <- function(n) {
  d <- expand.grid(item=1:24, participant=1:n)
  k <- (d$item-1L) %% 8L
  d$truth <- k < 4L
  d$evidence <- ifelse(d$truth, c("full","full","partial","absent")[k+1L],
                       c("partial","partial","misleading","absent")[pmax(1L,k-3L)])
  d$condition <- c("generic","scoped","links")[((d$item-1L)%/%8L+(d$participant-1L)%%3L)%%3L+1L]
  d
}
write.csv(allocation(3),file.path(out,"allocation_example.csv"),row.names=FALSE)
run_scenario <- function(s) {
  z <- grid[s,]; path <- file.path(out,sprintf("scenario_%02d_%d.rds",s,reps))
  if(file.exists(path)) return(readRDS(path))
  set.seed(20261111L+s*10000L)
  ds <- allocation(z$n); d <- subset(ds,!truth)
  d$participant <- factor(d$participant); d$item <- factor(d$item)
  d$condition <- factor(d$condition,levels=c("generic","scoped","links"))
  d$evidence <- factor(d$evidence,levels=c("partial","misleading","absent"))
  sdv <- switch(z$heterogeneity,low=c(.5,.4),central=c(1,.8),high=c(1.5,1.2))
  ans <- matrix(NA_real_,reps,5,dimnames=list(NULL,c("reject","estimate","se","failed","singular")))
  for(r in seq_len(reps)) {
    u <- rnorm(z$n,0,sdv[1]); v <- rnorm(12,0,sdv[2])
    eta <- qlogis(.5)+u[as.integer(d$participant)]+v[as.integer(d$item)] +
      ifelse(d$evidence=="misleading",-.4,ifelse(d$evidence=="absent",.3,0)) +
      ifelse(d$condition=="scoped" & d$evidence=="partial",log(z$OR),0)
    d$reject <- rbinom(nrow(d),1,plogis(eta))
    fit <- try(suppressWarnings(glmer(reject ~ condition*evidence+(1|participant)+(1|item),
      data=d,family=binomial,nAGQ=1,
      control=glmerControl(optimizer="bobyqa",optCtrl=list(maxfun=20000)))),silent=TRUE)
    if(inherits(fit,"try-error")) {ans[r,] <- c(0,NA,NA,1,NA);next}
    msgs <- fit@optinfo$conv$lme4$messages
    fail <- any(!grepl("boundary.*singular",msgs)) || fit@optinfo$conv$opt!=0
    est <- fixef(fit)["conditionscoped"]; se <- sqrt(diag(vcov(fit)))["conditionscoped"]
    ans[r,] <- c(as.numeric(!fail && abs(est/se)>qnorm(.975)),est,se,as.numeric(fail),as.numeric(isSingular(fit)))
  }
  rate <- mean(ans[,"reject"]); ok <- ans[,"failed"]==0
  result <- cbind(z,repetitions=reps,participant_sd=sdv[1],item_sd=sdv[2],
    rejection_rate=rate,mc_se=sqrt(rate*(1-rate)/reps),
    successful_fit_rejection_rate=if(any(ok))mean(ans[ok,"reject"]) else NA,
    convergence_failure_rate=mean(ans[,"failed"]),singular_rate=mean(ans[,"singular"],na.rm=TRUE),
    mean_log_odds=mean(ans[,"estimate"],na.rm=TRUE))
  saveRDS(result,path)
  write.csv(as.data.frame(ans),file.path(out,sprintf("draws_%02d_%d.csv",s,reps)),row.names=FALSE)
  result
}
res <- parallel::mclapply(seq_len(nrow(grid)),run_scenario,mc.cores=cores,mc.preschedule=FALSE)
if(any(vapply(res,inherits,logical(1),"try-error"))) stop("A simulation worker failed")
write.csv(do.call(rbind,res),file.path(out,sprintf("power_%d.csv",reps)),row.names=FALSE)
writeLines(capture.output(sessionInfo()),file.path(out,"R-session.txt"))
writeLines(c("Simulation only; no human observations.",
 "Two-sided Wald contrast alpha=.05: scoped vs generic, false sentences with valid partial evidence.",
 "Failed fits count as non-rejections in primary power; conditional fit power also shown.",
 "Baseline conditional rejection=.5; misleading -.4 logits; absent +.3; links=generic.",
 "No random treatment slopes, dropout or learning model; these are limitations.",
 "No sample-size recommendation without a minimum meaningful effect and independently validated stimuli."),
 file.path(out,"METHOD.txt"))
