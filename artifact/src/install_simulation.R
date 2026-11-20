# Install exact CRAN package versions from the recorded simulation environment.
# Base/recommended R packages require the matching R distribution if mismatched.
lock <- read.csv('results/revision/simulation/R-packages.csv',na.strings='NA')
for(i in seq_len(nrow(lock))) {
 name <- lock$Package[i]; wanted <- lock$Version[i]
 if(requireNamespace(name,quietly=TRUE) && as.character(packageVersion(name))==wanted) next
 if(!is.na(lock$Priority[i])) {
   warning(paste('R-distributed package version differs:',name,wanted,'; see R-session.txt'))
   next
 }
 tar <- sprintf('%s_%s.tar.gz',name,wanted); dest <- file.path(tempdir(),tar)
 urls <- c(paste0('https://cloud.r-project.org/src/contrib/',tar),
           paste0('https://cloud.r-project.org/src/contrib/Archive/',name,'/',tar))
 ok <- FALSE
 for(url in urls) {
   got <- try(suppressWarnings(download.file(url,dest,quiet=TRUE)),silent=TRUE)
   if(!inherits(got,'try-error') && got==0) {ok <- TRUE; break}
 }
 if(!ok) stop(paste('Cannot retrieve pinned package',tar))
 install.packages(dest,repos=NULL,type='source')
 if(!requireNamespace(name,quietly=TRUE) || as.character(packageVersion(name))!=wanted)
   stop(paste('Pinned installation failed:',name,wanted))
}
