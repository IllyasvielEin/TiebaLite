package com.huanchengfly.tieba.post.api.retrofit

/** Marks an individually audited read method, regardless of HTTP verb or body encoding. */
@Target(AnnotationTarget.FUNCTION)
@Retention(AnnotationRetention.RUNTIME)
annotation class BudgetedReadRequest
